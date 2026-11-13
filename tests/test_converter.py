"""Run with:  python -m pytest tests   (or simply: python tests/test_converter.py)"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from roman_urdu import ConvertOptions, Transliterator, convert_docx  # noqa: E402

TR = Transliterator()

SENTENCES = {
    "Mera khyal ha ke Pakistan aik khoobsurat mulk hai.":
        "میرا خیال ہے کہ پاکستان ایک خوبصورت ملک ہے۔",
    "kia tum kal aao ge? mujhe nai pata k wo kiya keh raha tha!!":
        "کیا تم کل آؤ گے؟ مجھے نہیں پتا کہ وہ کیا کہہ رہا تھا!!",
    "Assalam o Alaikum! Ap kaise hain? Main theek hun, shukriya.":
        "السلام علیکم! آپ کیسے ہیں؟ میں ٹھیک ہوں، شکریہ۔",
    "bht mjhe smjh nahi aya, bohaaaat mushkil tha":
        "بہت مجھے سمجھ نہیں آیا، بہت مشکل تھا",
    "PIA ki flight 3 ghante late thi":
        "پی آئی اے کی فلائٹ 3 گھنٹے لیٹ تھی",
    "is bare mein baat karein":
        "اس بارے میں بات کریں",
}


def test_sentences():
    for roman, urdu in SENTENCES.items():
        assert TR.convert(roman) == urdu, (roman, TR.convert(roman))


def test_spelling_variants():
    for variants, urdu in [(["kya", "kia", "kiya"], "کیا"),
                           (["nahi", "nahin", "nhi", "nai"], "نہیں"),
                           (["bohat", "bahut", "bohot", "bht"], "بہت"),
                           (["zaroori", "zaruri", "zarori"], "ضروری")]:
        for v in variants:
            assert TR.word(v) == urdu, v


def test_rules_for_unknown_words():
    from roman_urdu import rule_transliterate
    assert rule_transliterate("kitaab") == "کتاب"
    assert rule_transliterate("kitab") == "کتاب"          # lone "a" before final b read long
    assert rule_transliterate("ghaltiyan") == "غلتیاں"     # -iyan plural -> یاں
    assert rule_transliterate("dekhna") == "دیکھنا"
    assert rule_transliterate("gaye") == "گئے"


def test_url_and_email_untouched():
    out = TR.convert("dekhein www.example.com ya info@example.com")
    assert "www.example.com" in out and "info@example.com" in out


def test_urdu_digits():
    assert TR.convert("2026", urdu_digits=True) == "۲۰۲۶"


def test_docx_roundtrip(tmp_path=None):
    import tempfile
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp())
    src = ROOT / "samples" / "sample_roman.docx"
    if not src.exists():
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "samples" / "make_sample.py")], check=True)
    dst = tmp / "sample_test (Urdu).docx"
    stats = convert_docx(src, dst, TR, ConvertOptions())
    assert stats.paragraphs > 10
    xml = zipfile.ZipFile(dst).read("word/document.xml").decode("utf-8")
    assert "میرا پاکستان" in xml
    assert "خیال" in xml                         # word that was split across two runs
    assert "<w:bidi/>" in xml and "<w:rtl/>" in xml and "<w:bidiVisual/>" in xml
    assert "Jameel Noori Nastaleeq" in xml
    header = zipfile.ZipFile(dst).read("word/header1.xml").decode("utf-8")
    assert "نمونہ" in header


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
