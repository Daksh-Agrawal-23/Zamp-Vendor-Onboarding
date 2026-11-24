import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Real public cheque photos (12, local only): can extract_ifsc recover a code that exists in the RBI list?  Tesseract-only vs +RapidOCR."""
import glob, json
from ocr_ifsc import _passes, _pick
import pytesseract
from PIL import Image
from ocrgst import rapid_text

res = []
for p in sorted(glob.glob("data/real/docs_real/cheque_*.jpg")):
    im = Image.open(p)
    text = ""
    for q in _passes(im):
        for cfg in ("", "--psm 6", "--psm 11"):
            text += "\n" + pytesseract.image_to_string(q, config=cfg)
    t = _pick(text)
    r = _pick(rapid_text(im))
    res.append(dict(file=p.split("/")[-1], tesseract=t, rapid=r))
    print(res[-1], flush=True)
json.dump(res, open("data/real/eval_cheques_real.json", "w"), indent=1)
print(
    "tesseract",
    sum(1 for r in res if r["tesseract"][0]),
    "rapid",
    sum(1 for r in res if r["rapid"][0]),
    "either",
    sum(1 for r in res if r["tesseract"][0] or r["rapid"][0]),
    "of",
    len(res),
)
