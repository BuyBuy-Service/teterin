"""PDF -> картинки страниц и обзорные сетки для визуальной проверки.
    python report/render.py file.pdf out_dir [cols]"""
import sys
from pathlib import Path

import fitz  # pymupdf
from PIL import Image

pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 4
out.mkdir(parents=True, exist_ok=True)
for old in out.glob("*.png"):
    old.unlink()
doc = fitz.open(pdf)
pages = []
for i, page in enumerate(doc, 1):
    p = out / f"p{i:02d}.png"
    page.get_pixmap(dpi=110).save(p)
    pages.append(p)
# сетки по cols*2 страниц
per = cols * 2
for k in range(0, len(pages), per):
    ims = [Image.open(p) for p in pages[k:k + per]]
    w, h = ims[0].width // 2, ims[0].height // 2
    sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), "white")
    for j, im in enumerate(ims):
        sheet.paste(im.resize((w, h)), ((j % cols) * w, (j // cols) * h))
    sheet.save(out / f"sheet{k // per + 1}.png")
print(len(pages), "pages")
