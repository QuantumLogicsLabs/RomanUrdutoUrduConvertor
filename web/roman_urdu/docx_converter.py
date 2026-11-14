"""Convert a Roman Urdu Word document (.docx) into an Urdu one.

What happens to the document:
  * every piece of Roman Urdu text (body, tables, text boxes, headers, footers,
    footnotes, comments) is transliterated to Urdu script;
  * formatting is kept - bold, italic, colours, headings, lists, tables, images;
  * Urdu text gets the Nastaliq font (Jameel Noori Nastaleeq by default), the
    complex-script size/bold/italic Word uses for Urdu, and the ur-PK language;
  * paragraphs become right-to-left and tables are mirrored (first column on
    the right), like a document typed in Urdu from the start.

The .docx is edited at the XML level (it is a ZIP of XML files), so anything
this module does not touch survives unchanged.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from .transliterator import ARABIC_SCRIPT, Transliterator

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


W_P, W_R, W_T, W_PPR, W_RPR = _w("p"), _w("r"), _w("t"), _w("pPr"), _w("rPr")
SEP = "\x00"   # stands for a tab / line break / image inside a paragraph

# Parts whose text is converted; styles.xml and numbering.xml only get formatting.
TEXT_PARTS = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")

# Elements inside a paragraph that separate words (never merged into one word).
_SEPARATORS = {_w(t) for t in (
    "tab", "br", "cr", "ptab", "sym", "drawing", "pict", "object", "fldChar", "noBreakHyphen",
    "footnoteReference", "endnoteReference", "commentReference", "separator",
    "continuationSeparator", "pgNum", "dayShort", "monthShort", "yearShort",
)}
# Elements we never look inside for text.
_NO_DESCEND = {_w(t) for t in (
    "p", "pPr", "rPr", "txbxContent", "instrText", "delText", "delInstrText", "softHyphen",
)}
_SYMBOL_FONTS = {"symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings", "marlett",
                 "mt extra", "segoe ui symbol", "segoe mdl2 assets"}

# Child order required by the OOXML schema (Word rejects files with wrong order).
RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
             "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish",
             "webHidden", "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight",
             "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
             "eastAsianLayout", "specVanish", "oMath"]
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
             "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
             "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
             "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
             "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
             "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"]
TBLPR_ORDER = ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
               "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders",
               "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
               "tblPrChange"]
SECTPR_ORDER = ["headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz",
                "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt",
                "vAlign", "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid",
                "printerSettings", "sectPrChange"]


@dataclass
class ConvertOptions:
    font: str = "Jameel Noori Nastaleeq"
    scale: float = 1.3          # Nastaliq looks small: 11pt Calibri -> 14pt Jameel Noori
    urdu_digits: bool = False   # 2026 -> ۲۰۲۶
    language: str = "ur-PK"


@dataclass
class ConvertStats:
    paragraphs: int = 0
    words: int = 0


# ============================================================================
#  small XML helpers
# ============================================================================

def _local(el) -> str | None:
    tag = el.tag
    if isinstance(tag, str) and tag.startswith("{" + W_NS + "}"):
        return tag[len(W_NS) + 2:]
    return None


def _child(parent, tag: str, order: list[str]):
    """Return parent's w:<tag> child, creating it at the schema-correct position."""
    el = parent.find(_w(tag))
    if el is not None:
        return el
    el = etree.SubElement(parent, _w(tag))   # SubElement reuses the parent's "w:" prefix
    parent.remove(el)
    pos = order.index(tag)
    for i, child in enumerate(parent):
        name = _local(child)
        if name in order and order.index(name) > pos:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


def _first_child(parent, tag: str):
    """Return w:<tag> that must be the first child (pPr of w:p, rPr of w:r ...)."""
    el = parent.find(_w(tag))
    if el is None:
        el = etree.SubElement(parent, _w(tag))
        parent.remove(el)
        parent.insert(0, el)
    return el


def _set_on(el) -> None:
    """Turn an on/off property on (remove w:val="0"/"false")."""
    el.attrib.pop(_w("val"), None)


def _scaled(value: str | None, scale: float) -> str | None:
    if value is None or not value.isdigit():
        return value
    if scale == 1:
        return value
    points = max(1, round(int(value) * scale / 2))   # sizes are half-points; keep whole points
    return str(points * 2)


# ============================================================================
#  formatting
# ============================================================================

def _is_symbol_run(run) -> bool:
    rpr = run.find(W_RPR)
    fonts = rpr.find(_w("rFonts")) if rpr is not None else None
    if fonts is None:
        return False
    return any((fonts.get(_w(a)) or "").lower() in _SYMBOL_FONTS for a in ("ascii", "hAnsi"))


def _complex_script_props(rpr, opts: ConvertOptions, scale_latin: bool) -> None:
    """Font/size/bold/italic that Word uses for Urdu (complex script) text."""
    fonts = _child(rpr, "rFonts", RPR_ORDER)
    fonts.attrib.pop(_w("cstheme"), None)
    fonts.set(_w("cs"), opts.font)
    for latin, cs in (("b", "bCs"), ("i", "iCs")):
        el = rpr.find(_w(latin))
        if el is not None:
            target = _child(rpr, cs, RPR_ORDER)
            val = el.get(_w("val"))
            if val is None:
                target.attrib.pop(_w("val"), None)
            else:
                target.set(_w("val"), val)
    sz, szcs = rpr.find(_w("sz")), rpr.find(_w("szCs"))
    base = sz if sz is not None else szcs
    if base is not None:
        new = _scaled(base.get(_w("val")), opts.scale)
        if sz is not None and scale_latin:
            sz.set(_w("val"), new)
        _child(rpr, "szCs", RPR_ORDER).set(_w("val"), new)


def _make_urdu_rpr(rpr, opts: ConvertOptions) -> None:
    """Run properties for a run of Urdu text."""
    fonts = _child(rpr, "rFonts", RPR_ORDER)
    for attr in ("asciiTheme", "hAnsiTheme", "cstheme"):
        fonts.attrib.pop(_w(attr), None)
    for attr in ("ascii", "hAnsi"):
        fonts.set(_w(attr), opts.font)
    _complex_script_props(rpr, opts, scale_latin=True)
    _set_on(_child(rpr, "rtl", RPR_ORDER))
    _child(rpr, "lang", RPR_ORDER).set(_w("bidi"), opts.language)


def _format_run(run, opts: ConvertOptions) -> None:
    if _is_symbol_run(run):
        return
    text = "".join(t.text or "" for t in run.findall(W_T))
    rpr = _first_child(run, "rPr")
    if re.search(r"[A-Za-z]", text) and not ARABIC_SCRIPT.search(text):
        # Left in Latin script on purpose (URL, e-mail, a word you kept in English):
        # keep its Latin font and left-to-right direction.
        _complex_script_props(rpr, opts, scale_latin=False)
    else:
        _make_urdu_rpr(rpr, opts)


def _format_paragraph(p, opts: ConvertOptions) -> None:
    ppr = _first_child(p, "pPr")
    _set_on(_child(ppr, "bidi", PPR_ORDER))
    mark = ppr.find(W_RPR)                      # formatting of the paragraph mark / list number
    if mark is not None:
        _make_urdu_rpr(mark, opts)


# ============================================================================
#  text
# ============================================================================

def _collect_text(p) -> list[tuple[object | None, str]]:
    """Text pieces of one paragraph in reading order: (w:t element | None, text)."""
    items: list[tuple[object | None, str]] = []

    def walk(el):
        for child in el:
            tag = child.tag
            if not isinstance(tag, str):
                continue
            if tag == W_T:
                items.append((child, child.text or ""))
            elif tag in _SEPARATORS:
                items.append((None, SEP))
            elif tag in _NO_DESCEND:
                continue
            elif tag == W_R and _is_symbol_run(child):
                items.append((None, SEP))
            else:
                walk(child)

    walk(p)
    return items


def _convert_paragraph_text(p, tr: Transliterator, opts: ConvertOptions, stats: ConvertStats) -> None:
    items = _collect_text(p)
    if not any(node is not None and re.search(r"[A-Za-z0-9,.?;]", txt) for node, txt in items):
        return
    full = "".join(txt for _, txt in items)
    owner: list[int] = []
    for k, (node, txt) in enumerate(items):
        owner.extend([k if node is not None else -1] * len(txt))

    letters = [c for c in full if c.isascii() and c.isalpha()]
    mostly_caps = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.6

    new_text: list[list[str]] = [[] for _ in items]
    for seg in tr.segments(full, acronyms=not mostly_caps, urdu_digits=opts.urdu_digits):
        o = owner[seg.start] if seg.start < len(owner) else -1
        if o >= 0:
            new_text[o].append(seg.text)
    # A word split over several runs ("kha" + "yal") goes, whole, into the run
    # where it starts; the other runs give up their part of it.
    for k, (node, _) in enumerate(items):
        if node is not None:
            node.text = "".join(new_text[k])
            node.set(XML_SPACE, "preserve")
    stats.paragraphs += 1
    stats.words += len(re.findall(r"[A-Za-z]+", full))


# ============================================================================
#  parts
# ============================================================================

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True,
                          remove_blank_text=False)


def _parse(data: bytes):
    return etree.fromstring(data, _PARSER)


def _serialize(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _process_text_part(data: bytes, tr: Transliterator, opts: ConvertOptions, stats: ConvertStats) -> bytes:
    root = _parse(data)
    paragraphs = list(root.iter(W_P))
    for p in paragraphs:
        _convert_paragraph_text(p, tr, opts, stats)
    for r in list(root.iter(W_R)):
        _format_run(r, opts)
    for p in paragraphs:
        _format_paragraph(p, opts)
    for tbl in list(root.iter(_w("tbl"))):
        tblpr = _first_child(tbl, "tblPr")
        _set_on(_child(tblpr, "bidiVisual", TBLPR_ORDER))
    for sect in list(root.iter(_w("sectPr"))):
        _set_on(_child(sect, "bidi", SECTPR_ORDER))
    return _serialize(root)


def _process_styles(data: bytes, opts: ConvertOptions) -> bytes:
    """Give every style an Urdu (complex-script) font and size, and make new
    paragraphs right-to-left by default.  Latin fonts are left alone, so any
    English you type later still looks normal."""
    root = _parse(data)
    defaults = root.find(_w("docDefaults"))
    if defaults is None:
        defaults = etree.SubElement(root, _w("docDefaults"))
        root.remove(defaults)
        root.insert(0, defaults)
    rpr_default = _child(defaults, "rPrDefault", ["rPrDefault", "pPrDefault"])
    rpr = _child(rpr_default, "rPr", ["rPr"])
    if rpr.find(_w("sz")) is None and rpr.find(_w("szCs")) is None:
        _child(rpr, "szCs", RPR_ORDER).set(_w("val"), "20")      # Word's built-in default
    _complex_script_props(rpr, opts, scale_latin=False)
    _child(rpr, "lang", RPR_ORDER).set(_w("bidi"), opts.language)
    ppr_default = _child(defaults, "pPrDefault", ["rPrDefault", "pPrDefault"])
    _set_on(_child(_child(ppr_default, "pPr", ["pPr"]), "bidi", PPR_ORDER))

    for style in root.iter(_w("style")):
        style_rpr = style.find(W_RPR)
        if style_rpr is not None:
            _complex_script_props(style_rpr, opts, scale_latin=False)
    return _serialize(root)


def _process_numbering(data: bytes) -> bytes:
    """Bullets drawn with Symbol/Wingdings must keep that font in RTL lists."""
    root = _parse(data)
    for fonts in root.iter(_w("rFonts")):
        latin = fonts.get(_w("ascii")) or fonts.get(_w("hAnsi"))
        if latin and not fonts.get(_w("cs")):
            fonts.set(_w("cs"), latin)
    return _serialize(root)


# ============================================================================
#  public API
# ============================================================================

def convert_docx(src: str | Path, dst: str | Path, tr: Transliterator,
                 opts: ConvertOptions | None = None) -> ConvertStats:
    """Read Roman Urdu ``src`` (.docx) and write the Urdu version to ``dst``."""
    opts = opts or ConvertOptions()
    src, dst = Path(src), Path(dst)
    stats = ConvertStats()
    if src.resolve() == dst.resolve():
        raise ValueError("Output file must be different from the input file")

    with zipfile.ZipFile(src) as zin:
        entries = []
        for info in zin.infolist():
            if info.is_dir():
                continue
            data = zin.read(info.filename)
            name = info.filename
            if TEXT_PARTS.match(name):
                data = _process_text_part(data, tr, opts, stats)
            elif name == "word/styles.xml":
                data = _process_styles(data, opts)
            elif name == "word/numbering.xml":
                data = _process_numbering(data)
            entries.append((info, data))

    # write to a temp file first so a crash never leaves a half-written document
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=dst.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in entries:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = info.external_attr
                zout.writestr(zi, data)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return stats
