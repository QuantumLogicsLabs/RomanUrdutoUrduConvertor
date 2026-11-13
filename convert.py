"""Convert Roman Urdu Word documents to Urdu (Jameel Noori Nastaleeq).

Usage
-----
  python convert.py                       convert every .docx in the input\\ folder -> output\\
  python convert.py "My File.docx"        writes "My File (Urdu).docx" next to it
  python convert.py a.docx b.docx -o out\\ several files into a folder
  python convert.py --text "mera khyal ha ke ..."   quick test of a sentence

Options
-------
  --font NAME       Urdu font (default: Jameel Noori Nastaleeq)
  --scale 1.3       font-size multiplier for Urdu text (1 = keep sizes as they are)
  --urdu-digits     write numbers as ۱۲۳ instead of 123
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from roman_urdu import ConvertOptions, Transliterator, convert_docx

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
CUSTOM_WORDS = ROOT / "custom_words.txt"
SUFFIX = " (Urdu)"


def font_installed(name: str) -> bool:
    folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
               Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    needle = name.lower().replace(" ", "")
    for folder in folders:
        if folder.is_dir():
            for f in folder.iterdir():
                stem = f.stem.lower().replace(" ", "")
                if stem.startswith(needle[:12]):
                    return True
    return sys.platform != "win32"   # can't check on other systems - assume yes


def collect_inputs(args_inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    sources = [Path(p) for p in args_inputs] or [INPUT_DIR]
    for src in sources:
        if src.is_dir():
            paths.extend(sorted(p for p in src.glob("*.docx")
                                if not p.name.startswith("~$") and SUFFIX not in p.stem))
        elif src.suffix.lower() == ".doc":
            print(f"  ! {src.name}: old .doc format - open it in Word and 'Save As' .docx first")
        elif src.is_file():
            paths.append(src)
        else:
            print(f"  ! not found: {src}")
    return paths


def output_path(src: Path, out_arg: str | None, many: bool, default_dir: Path | None) -> Path:
    if out_arg:
        out = Path(out_arg)
        if many or out.is_dir() or not out.suffix:
            out.mkdir(parents=True, exist_ok=True)
            return out / f"{src.stem}{SUFFIX}.docx"
        return out
    if default_dir is not None:
        default_dir.mkdir(parents=True, exist_ok=True)
        return default_dir / f"{src.stem}{SUFFIX}.docx"
    return src.with_name(f"{src.stem}{SUFFIX}.docx")


def report_unknown(tr: Transliterator, limit: int = 40) -> None:
    if not tr.unknown:
        print("\nEvery word was found in the dictionary.")
        return
    print(f"\n{len(tr.unknown)} word(s) were not in the dictionary and were spelled by rules.")
    print("If any look wrong, add the correct spelling to custom_words.txt, e.g.  اردو = roman")
    print("and run the program again:\n")
    for word, count in tr.unknown.most_common(limit):
        print(f"   {word:<18} -> {tr.guesses[word]}" + (f"   (x{count})" if count > 1 else ""))
    if len(tr.unknown) > limit:
        print(f"   ... and {len(tr.unknown) - limit} more")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Convert Roman Urdu Word files to Urdu script.")
    ap.add_argument("inputs", nargs="*", help=".docx files or folders (default: the input folder)")
    ap.add_argument("-o", "--output", help="output .docx file, or a folder")
    ap.add_argument("--font", default="Jameel Noori Nastaleeq")
    ap.add_argument("--scale", type=float, default=1.3, help="Urdu font-size multiplier (default 1.3)")
    ap.add_argument("--urdu-digits", action="store_true", help="use Urdu digits ۰۱۲۳")
    ap.add_argument("--custom", default=str(CUSTOM_WORDS), help="your own word list")
    ap.add_argument("--text", help="convert this text and print it (no Word file)")
    args = ap.parse_args(argv)

    tr = Transliterator(custom_files=[args.custom])

    if args.text is not None:
        print(tr.convert(args.text, urdu_digits=args.urdu_digits))
        return 0

    files = collect_inputs(args.inputs)
    if not files:
        INPUT_DIR.mkdir(exist_ok=True)
        print(f"No .docx files found. Put your Roman Urdu Word files in:\n   {INPUT_DIR}\n"
              f"or drag a file onto 'Convert to Urdu.bat'.")
        return 1

    if not font_installed(args.font):
        print(f"  ! Font '{args.font}' does not seem to be installed - Word will show a "
              f"substitute font until you install it.\n")

    opts = ConvertOptions(font=args.font, scale=args.scale, urdu_digits=args.urdu_digits)
    default_dir = OUTPUT_DIR if not args.inputs else None
    failed = 0
    for src in files:
        dst = output_path(src, args.output, len(files) > 1, default_dir)
        try:
            stats = convert_docx(src, dst, tr, opts)
            print(f"  OK  {src.name}  ->  {dst}   ({stats.paragraphs} paragraphs, {stats.words} words)")
        except PermissionError:
            failed += 1
            print(f"  !!  {dst.name} is open in Word - close it and run again.")
        except Exception as exc:  # keep going with the other files
            failed += 1
            print(f"  !!  {src.name}: {exc}")

    report_unknown(tr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
