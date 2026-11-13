"""Website + API for the Roman Urdu -> Urdu converter.

Start it with   python web/app.py          (or double-click "Start Website.bat")
then open       http://127.0.0.1:8000
API docs at     http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from lxml import etree  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from roman_urdu import ConvertOptions, Transliterator, convert_docx  # noqa: E402
from roman_urdu.transliterator import ARABIC_SCRIPT, normalize_urdu  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
CUSTOM_WORDS = ROOT / "custom_words.txt"
MAX_UPLOAD = 20 * 1024 * 1024          # 20 MB .docx
MAX_UNZIPPED = 200 * 1024 * 1024       # refuse zip bombs
KEEP_DOCS = 40                         # converted files kept in memory
DOC_TTL = 60 * 60                      # ... for one hour
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(title="Roman Urdu → Urdu", version="1.0",
              description="Convert Roman Urdu text and Word documents to Urdu script.")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_lock = threading.Lock()
_base = Transliterator(custom_files=[CUSTOM_WORDS])
_docs: dict[str, dict] = {}


def translit() -> Transliterator:
    """A per-request copy (own unknown-word list) of the current dictionary."""
    return _base.fork()


def reload_dictionary() -> None:
    global _base
    fresh = Transliterator(custom_files=[CUSTOM_WORDS])
    with _lock:
        _base = fresh


# ============================================================================
#  pages
# ============================================================================

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "words": len(_base.words), "phrases": len(_base.phrases)}


# ============================================================================
#  text
# ============================================================================

class TextIn(BaseModel):
    text: str = Field(..., max_length=50_000, examples=["mera khyal ha ke ap theek hain"])
    urdu_digits: bool = False


@app.post("/api/convert")
def convert_text(body: TextIn):
    """Convert Roman Urdu text. Also returns the words that were not in the
    dictionary (spelled by rules) so they can be checked."""
    tr = translit()
    return {"urdu": tr.convert(body.text, urdu_digits=body.urdu_digits),
            "unknown": tr.unknown_words()}


# ============================================================================
#  Word documents
# ============================================================================

class DocOptions(BaseModel):
    scale: float = Field(1.3, ge=0.5, le=3)
    urdu_digits: bool = False


def _cleanup() -> None:
    now = time.time()
    for key in [k for k, d in _docs.items() if now - d["created"] > DOC_TTL]:
        _docs.pop(key, None)
    while len(_docs) > KEEP_DOCS:
        _docs.pop(next(iter(_docs)))


def _check_docx(data: bytes) -> None:
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 20 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                raise HTTPException(400, "This is not a Word .docx document.")
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise HTTPException(400, "Document is too large when unpacked.")
    except zipfile.BadZipFile:
        raise HTTPException(400, "This is not a valid .docx file. Old .doc files must be "
                                 "saved as .docx in Word first.")


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _preview(docx: bytes, limit: int = 80) -> list[dict]:
    """First paragraphs of the converted document, for showing in the page."""
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        root = etree.fromstring(z.read("word/document.xml"),
                                etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    out = []
    for p in root.iter(W + "p"):
        if p.getparent() is not None and p.getparent().tag == W + "txbxContent":
            continue
        # only this paragraph's own text, not text boxes anchored inside it
        text = "".join(t.text or "" for t in p.iter(W + "t") if next(t.iterancestors(W + "p")) is p)
        if not text.strip():
            continue
        style = p.find(f"{W}pPr/{W}pStyle")
        style = style.get(W + "val") if style is not None else ""
        in_table = any(a.tag == W + "tc" for a in p.iterancestors())
        is_list = p.find(f"{W}pPr/{W}numPr") is not None or style.lower().startswith("list")
        kind = ("title" if style.lower() == "title" else
                "heading" if style.lower().startswith("heading") else
                "cell" if in_table else
                "list" if is_list else "p")
        out.append({"text": text, "kind": kind})
        if len(out) >= limit:
            break
    return out


def _run_conversion(doc_id: str, opts: DocOptions) -> dict:
    entry = _docs.get(doc_id)
    if entry is None:
        raise HTTPException(404, "This file has expired - please upload it again.")
    tr = translit()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.docx"
        dst = Path(tmp) / "out.docx"
        src.write_bytes(entry["original"])
        try:
            stats = convert_docx(src, dst, tr, ConvertOptions(scale=opts.scale, urdu_digits=opts.urdu_digits))
        except etree.XMLSyntaxError:
            raise HTTPException(400, "The document is damaged and could not be read.")
        entry["converted"] = dst.read_bytes()
    return {
        "id": doc_id,
        "filename": entry["out_name"],
        "paragraphs": stats.paragraphs,
        "words": stats.words,
        "unknown": tr.unknown_words(),
        "preview": _preview(entry["converted"]),
        "download": f"/api/documents/{doc_id}/download",
    }


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...), scale: float = Form(1.3),
                          urdu_digits: bool = Form(False)):
    """Upload a Roman Urdu .docx; returns stats, a preview, words to check and a download link."""
    if not (file.filename or "").lower().endswith(".docx"):
        raise HTTPException(400, "Please choose a .docx Word file.")
    data = await file.read(MAX_UPLOAD + 1)
    _check_docx(data)
    _cleanup()
    stem = Path(file.filename).stem
    doc_id = uuid.uuid4().hex
    _docs[doc_id] = {"original": data, "converted": b"", "created": time.time(),
                     "out_name": f"{stem} (Urdu).docx"}
    return await run_in_threadpool(_run_conversion, doc_id, DocOptions(scale=scale, urdu_digits=urdu_digits))


@app.post("/api/documents/{doc_id}/convert")
def reconvert_document(doc_id: str, opts: DocOptions):
    """Convert an uploaded document again (e.g. after correcting words)."""
    return _run_conversion(doc_id, opts)


@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: str):
    entry = _docs.get(doc_id)
    if entry is None or not entry["converted"]:
        raise HTTPException(404, "This file has expired - please upload it again.")
    name = entry["out_name"]
    ascii_name = re.sub(r"[^A-Za-z0-9 ._()\-]", "_", name)
    return Response(entry["converted"], media_type=DOCX_MIME, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


# ============================================================================
#  your own words (custom_words.txt)
# ============================================================================

class WordEntry(BaseModel):
    roman: str = Field(..., min_length=1, max_length=80)
    urdu: str = Field(..., min_length=1, max_length=80)


class WordsIn(BaseModel):
    entries: list[WordEntry] = Field(..., min_length=1, max_length=500)


class WordOut(BaseModel):
    roman: str


def _read_custom() -> list[dict]:
    if not CUSTOM_WORDS.exists():
        return []
    entries = []
    for line in CUSTOM_WORDS.read_text(encoding="utf-8-sig").splitlines():
        body = line.split("#", 1)[0].strip()
        if "=" not in body:
            continue
        left, right = (p.strip() for p in body.split("=", 1))
        if ARABIC_SCRIPT.search(left) and not ARABIC_SCRIPT.search(right):
            urdu, romans = left, right
        else:
            romans, urdu = left, right
        for r in romans.split(","):
            if r.strip():
                entries.append({"roman": r.strip(), "urdu": urdu})
    return entries


@app.get("/api/custom-words")
def list_custom_words():
    return {"entries": _read_custom()}


@app.post("/api/custom-words")
def add_custom_words(body: WordsIn):
    """Save corrections to custom_words.txt. They win over the built-in dictionary."""
    lines = []
    for e in body.entries:
        roman = " ".join(e.roman.lower().split())
        urdu = normalize_urdu(" ".join(e.urdu.split()))
        if not re.fullmatch(r"[a-z' \-]+", roman):
            raise HTTPException(400, f"'{e.roman}': Roman spelling may only use English letters.")
        if "=" in urdu or "#" in urdu or "," in urdu:
            raise HTTPException(400, f"'{e.urdu}': please don't use = # or , in the Urdu word.")
        lines.append(f"{urdu} = {roman}")
    with _lock:
        text = CUSTOM_WORDS.read_text(encoding="utf-8-sig") if CUSTOM_WORDS.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        CUSTOM_WORDS.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")
    reload_dictionary()
    return {"saved": len(lines)}


@app.delete("/api/custom-words")
def delete_custom_word(body: WordOut):
    """Remove one Roman spelling from custom_words.txt."""
    target = body.roman.strip().lower()
    with _lock:
        if not CUSTOM_WORDS.exists():
            raise HTTPException(404, "Not found")
        kept, removed = [], False
        for line in CUSTOM_WORDS.read_text(encoding="utf-8-sig").splitlines():
            body_part = line.split("#", 1)[0]
            if "=" not in body_part or line.lstrip().startswith("#"):
                kept.append(line)
                continue
            left, right = (p.strip() for p in body_part.split("=", 1))
            urdu_left = ARABIC_SCRIPT.search(left) and not ARABIC_SCRIPT.search(right)
            urdu, romans = (left, right) if urdu_left else (right, left)
            variants = [r.strip() for r in romans.split(",") if r.strip()]
            remaining = [r for r in variants if r.lower() != target]
            if len(remaining) != len(variants):
                removed = True
                if remaining:
                    kept.append(f"{urdu} = {', '.join(remaining)}")
                continue
            kept.append(line)
        if not removed:
            raise HTTPException(404, "Not found")
        CUSTOM_WORDS.write_text("\n".join(kept) + "\n", encoding="utf-8")
    reload_dictionary()
    return {"removed": target}


# ============================================================================

def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="Run the Roman Urdu -> Urdu website")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to share on your network")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args()
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"\n  Roman Urdu -> Urdu website:  {url}\n  API docs:                    {url}/docs\n"
          f"  Press Ctrl+C to stop.\n")
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
