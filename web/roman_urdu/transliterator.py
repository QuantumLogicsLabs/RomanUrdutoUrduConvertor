"""Roman Urdu -> Urdu script transliteration engine.

For every word the engine tries, in order:

  1. custom_words.txt          (your own corrections - always win)
  2. the built-in dictionary   (data/dictionary.txt, with all spelling variants)
     - multi-word phrases are tried first, so "keh raha" -> "کہہ رہا" while a
       lone "keh" -> "کہ"
  3. fuzzy dictionary match    (bohattt -> bohat, mjhe -> mujhe, ...)
  4. phonetic rules            (fallback for words that are in no dictionary)

Words that reach step 4 are recorded in ``Transliterator.unknown`` so you can
review them and add the correct spelling to custom_words.txt.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DICTIONARY = PACKAGE_DIR / "data" / "dictionary.txt"

ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
# Arabic code points that look like Urdu letters but are the wrong characters.
_ARABIC_TO_URDU = str.maketrans({
    "ي": "ی",  # ي -> ی
    "ى": "ی",  # ى -> ی
    "ك": "ک",  # ك -> ک
    "ه": "ہ",  # ه -> ہ
})
URDU_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# How English capital letters are spoken in Urdu (for acronyms like PIA, NADRA).
LETTER_NAMES = {
    "A": "اے", "B": "بی", "C": "سی", "D": "ڈی", "E": "ای", "F": "ایف", "G": "جی",
    "H": "ایچ", "I": "آئی", "J": "جے", "K": "کے", "L": "ایل", "M": "ایم", "N": "این",
    "O": "او", "P": "پی", "Q": "کیو", "R": "آر", "S": "ایس", "T": "ٹی", "U": "یو",
    "V": "وی", "W": "ڈبلیو", "X": "ایکس", "Y": "وائی", "Z": "زیڈ",
}


# Short everyday words that stay words even when typed in CAPITALS ("KYA", "HAI");
# any other 2-3 letter all-caps token is treated as an acronym (PIA -> پی آئی اے).
COMMON_SHORT = set("""
ka ki ke ko se ne hai ha he hy ho hun to tu ye wo woh yeh aur or kya kia koi sab ab jab tab
hum tum aap ap mai me mein main na ni nai bhi hi par pe tak ek aik do us is un in jo ya aaj kal
din log dil tha thi the ga gi ge gya gai kar kr ja aa de le mat han ji yar acha bas fir kab kyu
kyo kon kis jis meri mera mere teri tera ap apna apni kam pas ab
""".split())

# "ke/kay/k" after these words is the conjunction کہ ("that"), not the
# possessive کے:  "mera khayal hai ke ..." -> "... ہے کہ ..."
KE_WORDS = {"ke", "kay", "ky", "k", "key", "kae"}
KE_CONJUNCTION_AFTER = set("""
ha hai he hy hae hay hei h tha thi the thay thy hain hen hein hn hun hoon ho hoga hogi honge
socha sochta sochti sochte socho kaha kehta kehti kehte kahte kaho suna pata pta lagta lagti
lagte laga lagi chahta chahti chahte chahiye maloom malum yaqeen umeed dekha dekho bataya batao
samjha samajhta samjhta samjhte samjho jaanta janta jante janti jaante bolo bola boli kahi
magar lekin dua shukar takay taa yeh ye jaise yani matlab
""".split())


def normalize_urdu(text: str) -> str:
    """Replace Arabic look-alike letters with the correct Urdu code points."""
    return text.translate(_ARABIC_TO_URDU)


def _key(word: str) -> str:
    return word.lower().replace("’", "'").replace("‘", "'").replace("`", "'")


def _fuzzy_key(key: str) -> str:
    """Spelling-insensitive key: bohatt/bohat, zaroor/zarur, mery/mere ..."""
    k = re.sub(r"['\-]", "", key)
    k = re.sub(r"(.)\1+", r"\1", k)                  # doubled letters
    k = k[0] + k[1:].replace("u", "o") if k else k  # zarur ~ zaror
    k = re.sub(r"(ay|ai|ey|y)$", "e", k)             # mery / meray ~ mere
    return k


def _skeleton(key: str) -> str:
    """Vowel-less skeleton used for chat abbreviations (bht, mjhe, krna)."""
    k = re.sub(r"['\-]", "", key)
    k = re.sub(r"(.)\1+", r"\1", k)
    return k[:1] + re.sub(r"[aeiou]", "", k[1:])


# ============================================================================
#  Phonetic rules (fallback)
# ============================================================================

_DIGRAPHS = ("chh", "kh", "gh", "sh", "ch", "th", "ph", "bh", "dh", "jh", "rh", "zh", "ck")
_CONSONANT = {
    "chh": "چھ", "kh": "خ", "gh": "غ", "sh": "ش", "ch": "چ", "th": "تھ", "ph": "پھ",
    "bh": "بھ", "dh": "دھ", "jh": "جھ", "rh": "ڑھ", "zh": "ژ", "ck": "ک",
    "b": "ب", "c": "ک", "d": "د", "f": "ف", "g": "گ", "h": "ہ", "j": "ج", "k": "ک",
    "l": "ل", "m": "م", "n": "ن", "p": "پ", "q": "ق", "r": "ر", "s": "س", "t": "ت",
    "v": "و", "w": "و", "x": "کس", "y": "ی", "z": "ز", "'": "ع",
}
# vowel cluster at the start of a word (followed by a consonant)
_V_INITIAL = {
    "a": "ا", "aa": "آ", "e": "ای", "ee": "ای", "i": "ا", "ii": "ای", "o": "او", "oo": "او",
    "u": "ا", "uu": "او", "ai": "ای", "ae": "ای", "ay": "ای", "ei": "ای", "ey": "ای",
    "au": "او", "ao": "او", "ou": "او", "aai": "آئی", "aae": "آئ", "aao": "آؤ",
    "ia": "ایا", "io": "ایو", "ie": "ای", "ua": "اوا", "oa": "اوا", "eo": "ایو",
}
# the whole word is a vowel cluster
_V_WHOLE = {
    "a": "آ", "aa": "آ", "o": "او", "oo": "او", "e": "اے", "ee": "ای", "i": "ای", "u": "او",
    "ae": "اے", "ai": "اے", "ay": "اے", "ei": "اے", "ey": "اے", "ii": "ای", "ao": "آؤ",
    "aao": "آؤ", "aai": "آئی", "aae": "آئے", "oe": "اوئے", "oy": "اوئے", "oi": "اوئی",
}
# between two consonants
_V_MEDIAL = {
    "a": "", "aa": "ا", "e": "ی", "ee": "ی", "i": "", "ii": "ی", "o": "و", "oo": "و",
    "u": "", "uu": "و", "ai": "ی", "ae": "ئ", "ay": "ی", "ei": "ی", "ey": "ی", "au": "و",
    "ou": "و", "ao": "اؤ", "oa": "وا", "ua": "وا", "ia": "یا", "ea": "یا", "io": "یو",
    "iu": "یو", "eo": "یو", "ie": "ی", "ue": "وئ", "ui": "وئ", "oi": "وئ", "oe": "وئ",
    "aai": "ائ", "aae": "ائ", "aao": "اؤ", "aau": "اؤ", "aay": "ائ", "aei": "ائ",
    "iy": "ی", "uo": "و", "y": "ی",
}
# at the end of the word
_V_FINAL = {
    "a": "ا", "aa": "ا", "e": "ے", "ee": "ی", "i": "ی", "ii": "ی", "o": "و", "oo": "و",
    "u": "و", "uu": "و", "ai": "ائی", "ae": "ئے", "ay": "ے", "ey": "ے", "ei": "ے",
    "au": "و", "ou": "و", "ao": "اؤ", "aao": "اؤ", "aoo": "اؤ", "aai": "ائی", "aae": "ائے",
    "aay": "ائے", "aey": "ئے", "ia": "یا", "ie": "یے", "io": "یو", "iu": "یو", "ua": "وا",
    "ue": "وئے", "ui": "وئی", "oi": "وئی", "oe": "وئے", "oa": "وا", "ea": "یا", "eo": "یو",
    "oy": "وئی", "uy": "وئی", "iy": "ی", "y": "ے", "eey": "ی", "uaa": "وا", "iaa": "یا",
}
# vowel cluster + a final "n" (noon ghunna ں where Urdu uses it)
_V_NASAL = {
    "aa": "ان", "e": "یں", "ee": "ین", "ii": "ین", "o": "وں", "oo": "ون", "u": "وں",
    "uu": "ون", "ai": "یں", "ei": "یں", "ay": "یں", "ey": "یں", "ae": "ئیں", "aae": "ائیں",
    "aai": "ائیں", "aei": "ائیں", "au": "ون", "ou": "ون", "ao": "اؤں", "aao": "اؤں",
    "ia": "یاں", "io": "یوں", "iu": "یوں", "ua": "واں", "ue": "وئیں", "oe": "وئیں",
    "ui": "وئیں", "oi": "وئیں", "ie": "یں", "ea": "یاں", "eo": "یوں", "y": "یں",
}
# final consonants after which a lone "a" in the last syllable is usually long
# (kitab -> کتاب, sawal -> سوال, insan -> انسان) rather than short (nazar -> نظر).
_LONG_A_BEFORE = {"b", "m", "n", "l", "s", "sh", "z", "j", "d", "f"}


def _segment(word: str) -> list[list[str]]:
    """Split a lowercase word into ['C', consonant] / ['V', vowel-cluster] units."""
    units: list[list[str]] = []
    i, n = 0, len(word)
    while i < n:
        ch = word[i]
        if ch in "aeiou":
            j = i
            while j < n and word[j] in "aeiou":
                j += 1
            units.append(["V", word[i:j]])
            i = j
            continue
        if ch in "yw":
            nxt = word[i + 1] if i + 1 < n else ""
            if nxt and nxt in "aeiou":            # glide before a vowel: ya, wa
                units.append(["C", ch])
            elif units and units[-1][0] == "V":   # part of the vowel: ay, ey, ow
                units[-1][1] += "y" if ch == "y" else "o"
            elif ch == "y":                       # y used as a vowel: hy, mery
                units.append(["V", "y"])
            else:
                units.append(["C", ch])
            i += 1
            continue
        for dg in _DIGRAPHS:
            if word.startswith(dg, i):
                units.append(["C", dg])
                i += len(dg)
                break
        else:
            units.append(["C", ch])
            i += 1
    return units


def rule_transliterate(word: str) -> str:
    """Phonetic Roman -> Urdu conversion for a single lowercase word."""
    w = re.sub(r"[^a-z']", "", word.lower())
    w = re.sub(r"([bcdfgjklmnpqrstvxz])\1", r"\1", w)          # accha -> acha
    w = re.sub(r"(chh|ch|kh|gh|sh|th|ph|bh|dh|jh)\1", r"\1", w)
    w = re.sub(r"([aeiouy])\1{2,}", r"\1\1", w)                 # bohaaat -> bohaat
    w = w.strip("'")
    if not w:
        return word
    if "ight" in w:                                              # flight, light, night
        head, _, tail = w.partition("ight")
        return (rule_transliterate(head) if head else "ا") + "ائٹ" + (rule_transliterate(tail) if tail else "")
    units = _segment(w)
    n_vowels = sum(1 for u in units if u[0] == "V")
    last = len(units) - 1
    out: list[str] = []
    idx = 0
    while idx <= last:
        kind, s = units[idx]
        prev = units[idx - 1] if idx > 0 else None
        nxt = units[idx + 1] if idx < last else None
        nxt2 = units[idx + 2] if idx + 1 < last else None

        if kind == "C":
            out.append(_consonant(s, idx, last, prev, nxt, nxt2))
            idx += 1
            continue

        # ---- vowel cluster -------------------------------------------------
        # consonant + y/w glide + a  ->  long a   (pyar, khyal, swal, jwab)
        after_glide = (prev is not None and prev[0] == "C" and prev[1] in ("y", "w")
                       and idx >= 2 and units[idx - 2][0] == "C")
        # u/o before "y + front vowel" is written و and the y becomes ئ (huye -> ہوئے)
        if s in ("u", "o", "oo") and nxt == ["C", "y"] and nxt2 and nxt2[0] == "V" and nxt2[1][0] in "ei":
            out.append("و" if idx else "او")
            idx += 1
            continue

        nasal_end = nxt == ["C", "n"] and idx + 1 == last
        if idx == 0 and idx == last:
            out.append(_V_WHOLE.get(s, "ا" + _V_MEDIAL.get(s, "")))
        elif idx == 0:
            if s == "e" and nxt == ["C", "h"]:
                out.append("ا")                                  # ehsas -> احساس-like
            else:
                out.append(_V_INITIAL.get(s, "ا" + _V_MEDIAL.get(s[1:], "")))
            if nasal_end:
                out.append("ن")
                idx += 1
        elif nasal_end:
            if s == "a" and prev == ["C", "y"] and idx >= 2 and units[idx - 2] == ["V", "i"]:
                out.append("اں")                                 # larkiyan -> لڑکیاں
            elif s == "a":
                out.append("ان" if (n_vowels >= 2 or after_glide) else "ن")
            elif s == "i":
                out.append("یں" if n_vowels >= 2 else "ن")
            else:
                out.append(_V_NASAL.get(s, _V_MEDIAL.get(s, "") + "ں"))
            idx += 1
        elif idx == last:
            out.append(_V_FINAL.get(s, _V_MEDIAL.get(s[:-1], "") + _V_FINAL.get(s[-1], "")))
        else:
            out.append(_medial_vowel(s, idx, last, units, n_vowels, after_glide, nxt, nxt2))
        idx += 1
    return "".join(out)


def _consonant(s, idx, last, prev, nxt, nxt2) -> str:
    if s == "rh":
        # "rh" after a vowel is ڑھ (parhna); at the start / after a consonant it is
        # chat shorthand for "rah" (rha -> رہا, rhe -> رہے).
        return "رہ" if prev is None or prev[0] == "C" else "ڑھ"
    if s == "kh":
        # Hindi verbs keep an aspirated کھ: dekh, likh, rakh, dekhna, aankh
        if idx == last and prev is not None and (prev[0] == "C" or prev[1] in ("a", "e", "i", "u", "o", "aa", "oo")):
            return "کھ"
        if nxt == ["C", "n"]:
            return "کھ"
        return "خ"
    if s == "y" and prev is not None and prev[0] == "V" and nxt is not None and nxt[0] == "V":
        if prev[1] in ("a", "aa", "u", "o", "oo", "uu") and nxt[1][0] in "ei":
            return "ئ"                                   # gaye -> گئے, aaye -> آئے
    if s == "n" and idx == last and prev is not None and prev[0] == "C":
        return "ن"
    return _CONSONANT.get(s, s)


def _medial_vowel(s, idx, last, units, n_vowels, after_glide, nxt, nxt2) -> str:
    if s == "a":
        if after_glide:
            return "ا"
        # last syllable "a" before a single final consonant: kitab, sawal, insan
        if (n_vowels >= 2 and idx + 1 == last and nxt is not None and nxt[0] == "C"
                and nxt[1] in _LONG_A_BEFORE):
            return "ا"
        # Arabic CiCaCat pattern: ijazat, adalat, mulaqat, shikayat -> long middle a
        if (n_vowels >= 3 and idx + 3 == last and nxt is not None and nxt[0] == "C"
                and units[idx + 2] == ["V", "a"] and units[last] == ["C", "t"]):
            return "ا"
        return ""
    if s == "e" and nxt == ["C", "h"]:
        return ""                                        # kehna -> کہنا, shehar -> شہر
    return _V_MEDIAL.get(s, "".join(_V_MEDIAL.get(c, "") for c in s))


# ============================================================================
#  Tokenising running text
# ============================================================================

_PROTECTED = re.compile(
    r"(?:https?://|www\.)[^\s\x00]+"                       # URLs
    r"|[^\s\x00@]+@[^\s\x00@]+\.[A-Za-z]{2,}",            # e-mail addresses
    re.IGNORECASE,
)
_TOKEN = re.compile(
    r"(?P<word>[A-Za-z]+(?:['’][A-Za-z]+)*(?:-[eE]-[A-Za-z]+(?:['’][A-Za-z]+)*)*)"
    r"|(?P<num>\d+(?:[.,:/]\d+)*)"
    r"|(?P<ws>[ \t ]+)"
    r"|(?P<other>.)",
    re.DOTALL,
)
_PUNCT = {",": "،", "?": "؟", ";": "؛"}
_CLOSERS = {")", "]", "\"", "'", "”", "’", ".", "!", "?"}


@dataclass
class Segment:
    """A piece of converted text: original span [start, end) -> new text."""
    start: int
    end: int
    text: str


class Transliterator:
    def __init__(self, custom_files: Iterable[str | Path] = (), dictionary: str | Path = DEFAULT_DICTIONARY):
        self.words: dict[str, str] = {}
        self.phrases: dict[tuple[str, ...], str] = {}
        self.max_phrase = 1
        self.unknown: Counter[str] = Counter()
        self.guesses: dict[str, str] = {}
        self._custom_keys: set[str] = set()
        self.load(dictionary, override=False)
        for path in custom_files:
            if Path(path).is_file():
                self.load(path, override=True)
        self._build_fuzzy_index()

    def fork(self) -> "Transliterator":
        """Cheap copy that shares the dictionaries but has its own unknown-word
        list - one per web request, so users don't see each other's words."""
        new = object.__new__(Transliterator)
        new.__dict__.update(self.__dict__)
        new.unknown = Counter()
        new.guesses = {}
        return new

    def unknown_words(self) -> list[dict]:
        return [{"roman": w, "guess": self.guesses[w], "count": c} for w, c in self.unknown.most_common()]

    # ---------------------------------------------------------------- loading
    def load(self, path: str | Path, override: bool) -> None:
        text = Path(path).read_text(encoding="utf-8-sig")
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            left, right = (p.strip() for p in line.split("=", 1))
            if not left or not right:
                continue
            # The side written in Urdu script is the output.  If neither side is
            # Urdu (e.g. "Microsoft = Microsoft") the right-hand side is output.
            if ARABIC_SCRIPT.search(left) and not ARABIC_SCRIPT.search(right):
                output, romans = left, right
            else:
                romans, output = left, right
            output = normalize_urdu(output)
            for variant in romans.split(","):
                parts = tuple(_key(p) for p in variant.split())
                if not parts:
                    continue
                if len(parts) == 1:
                    if override or parts[0] not in self.words:
                        self.words[parts[0]] = output
                    if override:
                        self._custom_keys.add(parts[0])
                else:
                    if override or parts not in self.phrases:
                        self.phrases[parts] = output
                    self.max_phrase = max(self.max_phrase, len(parts))
        if hasattr(self, "_fuzzy"):
            self._build_fuzzy_index()

    def _build_fuzzy_index(self) -> None:
        fuzzy: dict[str, set[str]] = {}
        skel: dict[str, set[str]] = {}
        for key, out in self.words.items():
            fuzzy.setdefault(_fuzzy_key(key), set()).add(out)
            s = _skeleton(key)
            if len(s) >= 3:
                skel.setdefault(s, set()).add(out)
        # only keep keys that point to exactly one Urdu word
        self._fuzzy = {k: next(iter(v)) for k, v in fuzzy.items() if len(v) == 1}
        self._skel = {k: next(iter(v)) for k, v in skel.items() if len(v) == 1}

    # ------------------------------------------------------------ single word
    def word(self, token: str, acronyms: bool = True, record: bool = True) -> str:
        if re.search(r"-[eE]-", token):                     # izafat: talib-e-ilm
            parts = [self.word(p, acronyms, record) for p in re.split(r"-[eE]-", token)]
            out = parts[0]
            for nxt in parts[1:]:
                if out.endswith("ہ"):
                    out = out[:-1] + "ۂ"
                elif out.endswith(("ا", "و")):
                    out += "ئے"
                else:
                    out += "ِ"
                out += " " + nxt
            return out

        key = _key(token)
        if acronyms and token.isupper() and token.isalpha() and 2 <= len(token) <= 5:
            if (len(token) <= 3 and key not in COMMON_SHORT) or key not in self.words:
                return " ".join(LETTER_NAMES[c] for c in token)
        hit = self.words.get(key) or self.words.get(key.replace("'", ""))
        if hit:
            return hit
        squeezed = re.sub(r"(.)\1{2,}", r"\1", key)          # bohaaat -> bohat
        hit = self.words.get(squeezed) or self._fuzzy.get(_fuzzy_key(key))
        if not hit and len(re.findall(r"[aeiou]", key)) <= 1:
            hit = self._skel.get(_skeleton(key))              # bht, mjhe, smjh
        if hit:
            return hit
        guess = rule_transliterate(key)
        if record:
            self.unknown[key] += 1
            self.guesses[key] = guess
        return guess

    # ----------------------------------------------------------- running text
    def segments(self, text: str, acronyms: bool = True, urdu_digits: bool = False) -> list[Segment]:
        """Convert ``text`` and return segments that map original spans to Urdu."""
        segs: list[Segment] = []
        pos = 0
        for m in _PROTECTED.finditer(text):
            segs.extend(self._plain_segments(text[pos:m.start()], pos, acronyms, urdu_digits))
            segs.append(Segment(m.start(), m.end(), m.group()))
            pos = m.end()
        segs.extend(self._plain_segments(text[pos:], pos, acronyms, urdu_digits))
        return segs

    def convert(self, text: str, acronyms: bool = True, urdu_digits: bool = False) -> str:
        return "".join(s.text for s in self.segments(text, acronyms, urdu_digits))

    def _plain_segments(self, text, offset, acronyms, urdu_digits) -> list[Segment]:
        tokens = [(m.lastgroup, m.start() + offset, m.end() + offset, m.group())
                  for m in _TOKEN.finditer(text)]
        segs: list[Segment] = []
        prev_word = ""                     # previous word in the same clause
        i = 0
        while i < len(tokens):
            kind, start, end, tok = tokens[i]
            if kind == "word":
                matched = self._match_phrase(tokens, i)
                if matched:
                    last_idx, output = matched
                    segs.append(Segment(start, tokens[last_idx][2], output))
                    prev_word = _key(tokens[last_idx][3])
                    i = last_idx + 1
                    continue
                key = _key(tok)
                if key in KE_WORDS and prev_word in KE_CONJUNCTION_AFTER and key not in self._custom_keys:
                    out = "کہ"
                else:
                    out = self.word(tok, acronyms)
                segs.append(Segment(start, end, out))
                prev_word = key
                i += 1
                continue
            if kind == "other" and tok not in ",،":
                prev_word = ""
            if kind == "num":
                segs.append(Segment(start, end, tok.translate(URDU_DIGITS) if urdu_digits else tok))
            elif kind == "ws":
                segs.append(Segment(start, end, tok))
            else:
                prev = tokens[i - 1] if i else None
                nxt = tokens[i + 1] if i + 1 < len(tokens) else None
                segs.append(Segment(start, end, self._punct(tok, prev, nxt)))
            i += 1
        return segs

    def _match_phrase(self, tokens, i):
        if self.max_phrase < 2:
            return None
        cand = [i]
        k = i
        while (len(cand) < self.max_phrase and k + 2 < len(tokens)
               and tokens[k + 1][0] == "ws" and tokens[k + 2][0] == "word"):
            k += 2
            cand.append(k)
        for length in range(len(cand), 1, -1):
            key = tuple(_key(tokens[j][3]) for j in cand[:length])
            if key in self.phrases:
                return cand[length - 1], self.phrases[key]
        return None

    @staticmethod
    def _punct(ch, prev, nxt) -> str:
        if ch in _PUNCT:
            return _PUNCT[ch]
        if ch == ".":
            # full stop after a word -> Urdu full stop "۔"; keep "." in 3.5, 1. etc.
            if prev is not None and (prev[0] == "word" or prev[3] in _CLOSERS):
                return "۔"
            return ch
        if ch == "-" and prev is not None and nxt is not None and prev[0] == "word" and nxt[0] == "word":
            return " "                                       # khuda-hafiz -> خدا حافظ
        return ch
