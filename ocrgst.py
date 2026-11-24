"""GSTIN candidates from OCR text, tolerant of what OCR actually does to them: spaces/newlines inside, O/0, S/5, Z/2 swaps,
one stray extra character. Every accepted value must pass the GSTIN check character, so a misread cannot become a wrong-but-valid number
unless it also satisfies a 1-in-36 checksum AND the position pattern AND sits right after a GSTIN label."""

import re
from validators import validate_gstin, canonicalise_gstin

LABELS = ("GSTIN", "GSTN", "GSTINUIN", "UIN", "REGISTRATIONNUMBER", "REGISTRATIONNO", "GSTNO")


def _fix(tok):
    c = canonicalise_gstin(tok)
    return c if validate_gstin(c)[0] else None


def candidates(text):
    """-> dict gstin -> how ('exact' | 'repaired')"""
    t = (text or "").upper()
    out = {}
    flat = re.sub(r"[^0-9A-Z]", "", t)
    for i in range(len(flat) - 14):  # unlabelled: exact only
        w = flat[i : i + 15]
        if w[:2].isdigit() and validate_gstin(w)[0]:
            out[w] = "exact"
    for lab in LABELS:
        for m in re.finditer(lab, flat):
            seg = flat[m.end() : m.end() + 20]
            found = set()
            for off in range(0, 4):
                tok = seg[off : off + 15]
                if len(tok) == 15 and (f := _fix(tok)):
                    found.add(f)
                tok16 = seg[off : off + 16]
                if len(tok16) == 16:
                    for j in range(16):
                        if f := _fix(tok16[:j] + tok16[j + 1 :]):
                            found.add(f)
            if len(found) == 1:
                g = next(iter(found))
                out.setdefault(g, "repaired")
    return out


_RAPID = None


def rapid_text(img):
    """Second OCR engine (RapidOCR, ONNX, models bundled in the package). Much better than Tesseract on phone photos (see eval_quality)."""
    global _RAPID
    import numpy as np

    if _RAPID is None:
        from rapidocr_onnxruntime import RapidOCR

        _RAPID = RapidOCR()
    res, _ = _RAPID(np.array(img.convert("RGB")))
    return "\n".join(x[1] for x in (res or []))
