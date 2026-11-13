# Roman Urdu → Urdu (Word documents)

Write a Word file in Roman Urdu, run the program, and get the same Word file
in Urdu script, in the **Jameel Noori Nastaleeq** font.

```
Mera khyal ha ke Pakistan aik khoobsurat mulk hai.
        ↓
میرا خیال ہے کہ پاکستان ایک خوبصورت ملک ہے۔
```

## How to use

**Easiest:** put your `.docx` files in the `input` folder and double-click
**`Convert to Urdu.bat`**. The Urdu files appear in `output`.
You can also drag a `.docx` file onto `Convert to Urdu.bat`. The result
is saved next to it as `Name (Urdu).docx`.

From a terminal:

```bash
python convert.py                          # every .docx in input\ → output\
python convert.py "My Letter.docx"         # → "My Letter (Urdu).docx"
python convert.py a.docx -o result.docx    # choose the output name
python convert.py --text "kia haal hai"    # quick test, no Word file
```

| Option | Meaning |
|---|---|
| `--scale 1.3` | Urdu font-size multiplier (default 1.3, so 11pt becomes 14pt). Use `--scale 1` to keep sizes. |
| `--urdu-digits` | Write numbers as ۲۰۲۶ instead of 2026 |
| `--font "Name"` | Use another Urdu font |

First-time setup: `pip install -r requirements.txt`

## Website

Double-click **`Start Website.bat`** (or run `python web/app.py --open`) and the
site opens at <http://127.0.0.1:8000>.

- **Text**: type Roman Urdu and the Urdu appears as you type. Copy it with one click.
- **Word file**: drop a `.docx` to see a preview and download the Urdu version.
- **Words to check**: words that weren't in the dictionary are listed with
  their guessed spelling. Correct them, press *Save*, and the conversion
  re-runs. Corrections go into `custom_words.txt`, so the desktop program
  uses them too.
- **My words**: see, add or remove your own words.

The page uses Jameel Noori Nastaleeq when it's installed on the viewer's
computer and Noto Nastaliq Urdu otherwise. Light and dark themes are
supported, and it works on phones.

To use it from your phone or other computers on the same Wi-Fi, run
`python web/app.py --host 0.0.0.0` and open `http://<your-PC-IP>:8000`. Anyone
who can open the site can also edit `custom_words.txt`, so only do this on a
network you trust.

### API

Interactive docs are at <http://127.0.0.1:8000/docs>.

| Method | Path | Does |
|---|---|---|
| `POST` | `/api/convert` | `{"text": "...", "urdu_digits": false}` → `{"urdu", "unknown"}` |
| `POST` | `/api/documents` | form upload `file` (+ `scale`, `urdu_digits`) → preview, stats, words to check, download link |
| `POST` | `/api/documents/{id}/convert` | convert the uploaded file again (after corrections) |
| `GET` | `/api/documents/{id}/download` | the Urdu `.docx` (kept for 1 hour) |
| `GET`/`POST`/`DELETE` | `/api/custom-words` | list / add / remove your words |

## What gets converted

- All text: body, headings, tables, lists, text boxes, headers, footers,
  footnotes, comments, hyperlink text
- Formatting is kept: bold, italic, colours, sizes, styles, images
- Paragraphs become right-to-left, tables are mirrored (first column on the
  right), and bullets and numbers move to the right side
- Left as they are: URLs and e-mail addresses. Acronyms are spelled out the
  Urdu way (PIA → پی آئی اے)
- Punctuation: `, ? ; .` become `، ؟ ؛ ۔`

## Fixing a word that came out wrong

After every run the program lists the words it **didn't** find in its
dictionary and had to guess. If a guess is wrong, add a line to
**`custom_words.txt`** and run again:

```
نادرا = nadra
کہہ رہا = keh raha          ← phrases work too
Microsoft = Microsoft       ← keep a word in English
```

Your words always win over the built-in dictionary.

## How it works

`roman_urdu/transliterator.py` looks up every word in this order:

1. `custom_words.txt` (your corrections)
2. `roman_urdu/data/dictionary.txt`: ~1,450 Urdu words with ~3,900 Roman
   spellings (`kya, kia, kiya → کیا`), plus phrases that settle ambiguous words
   (`keh raha → کہہ رہا`, `ke bare mein → کے بارے میں`). A small context rule
   turns `ke` into کہ after verbs (`khayal hai ke → خیال ہے کہ`).
3. A fuzzy match for messy spellings (`bohaaaat`, `bht`, `mjhe`, `smjh`)
4. Phonetic rules as the last resort (`kitab → کتاب`, `larkiyan → لڑکیاں`)

`roman_urdu/docx_converter.py` edits the Word file's XML directly, so
anything it doesn't touch stays exactly as it was. A word that Word split
across two pieces of formatting is still converted as one word.

## Limits

- Roman Urdu doesn't show which Urdu letter is meant (س/ص/ث, ز/ذ/ض/ظ, ت/ط,
  ہ/ح), so words outside the dictionary may use the wrong one. Add them to
  `custom_words.txt`.
- The old `.doc` format isn't supported. In Word, use *Save As → .docx* first.
- Charts and SmartArt text are not converted.

## Tests

```bash
python tests/test_converter.py      # or: python -m pytest tests
python samples/make_sample.py       # rebuilds samples/sample_roman.docx
```
