"""Create samples/sample_roman.docx - a Roman Urdu test document.

    python samples/make_sample.py
    python convert.py samples/sample_roman.docx
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

OUT = Path(__file__).resolve().parent / "sample_roman.docx"

doc = Document()
section = doc.sections[0]
section.header.paragraphs[0].text = "Roman Urdu se Urdu - Namoona Document"
section.footer.paragraphs[0].text = "Shukriya - Allah Hafiz"

doc.add_heading("Mera Pakistan", level=0)
date = doc.add_paragraph("Tareekh: 13 November 2026")
date.alignment = WD_ALIGN_PARAGRAPH.RIGHT

doc.add_heading("Taaruf", level=1)
p = doc.add_paragraph()
p.add_run("Mera khyal ha ke ")
p.add_run("Pakistan").bold = True
p.add_run(" aik bohat khoobsurat mulk hai. Yahan ke log ")
p.add_run("mehman nawaz").italic = True
p.add_run(" hain aur har kisi ki madad karte hain.")

p = doc.add_paragraph()
p.add_run("Aaj kal mehngai bohot zyada ho gayi hai, lekin hum umeed nahi chorte. Hamara kha")
p.add_run("yal hai ke agar hum mil kar kaam karein to kuch bhi mumkin hai.")   # word split over 2 runs
p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

doc.add_heading("Achi Aadatein", level=1)
for item in ["Taleem sab ke liye zaroori hai", "Sehat ka khayal rakhein", "Waqt ki qadar karein"]:
    doc.add_paragraph(item, style="List Bullet")
for item in ["Subah jaldi uthna", "Namaz parhna", "Rozana kitab parhna"]:
    doc.add_paragraph(item, style="List Number")

doc.add_heading("Dost aur Shehar", level=1)
table = doc.add_table(rows=1, cols=3)
table.style = "Table Grid"
for cell, text in zip(table.rows[0].cells, ["Naam", "Shehar", "Umar"]):
    cell.text = text
    cell.paragraphs[0].runs[0].bold = True
for row in [("Ali", "Lahore", "25"), ("Ayesha", "Karachi", "30"), ("Usman", "Islamabad", "28")]:
    cells = table.add_row().cells
    for cell, text in zip(cells, row):
        cell.text = text

doc.add_heading("Chat ki Zaban", level=1)
doc.add_paragraph("kia tum kal aao ge? mujhe nai pata k wo kiya keh raha tha!!")
p = doc.add_paragraph()
r = p.add_run("bht mjhe smjh nahi aya, bohaaaat mushkil tha")
r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
r.font.size = Pt(13)
doc.add_paragraph("PIA ki flight 3 ghante late thi... Mazeed maloomat ke liye www.example.com dekhein.")

c = doc.add_paragraph("Assalam o Alaikum! Ap kaise hain? Main theek hun, shukriya.")
c.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.save(OUT)
print("written", OUT)
