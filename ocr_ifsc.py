"""IFSC extraction from a cheque image: multi-pass OCR + dictionary-assisted repair against the RBI list."""

import re, itertools
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from validators import validate_ifsc, ifsc_exists

_SWAP = {
    "0": "O",
    "O": "0",
    "1": "I",
    "I": "1",
    "5": "S",
    "S": "5",
    "8": "B",
    "B": "8",
    "2": "Z",
    "Z": "2",
    "6": "G",
    "G": "6",
}


def _passes(im):
    g = ImageOps.autocontrast(im.convert("L"))
    yield g
    for s in (2, 3):
        big = g.resize((g.width * s, g.height * s), Image.LANCZOS)
        yield big
        yield big.filter(ImageFilter.SHARPEN)
        yield big.point(lambda p: 255 if p > 150 else 0)


def _candidates(tok):
    """Normalise 11-char token: 5th char is always 0; branch part may be digits (usually) or letters."""
    tok = re.sub(r"[^A-Z0-9]", "", tok.upper())
    if len(tok) != 11:
        return set()
    base = tok[:4] + "0" + tok[5:]
    outs = {base}
    for i, ch in enumerate(base):
        if i == 4 or ch not in _SWAP:
            continue
        # letters in the bank code, digits in the branch code are the likely truth
        outs.add(base[:i] + _SWAP[ch] + base[i + 1 :])
    # allow two swaps in the branch part (OCR often mangles several digits)
    for i, j in itertools.combinations(range(5, 11), 2):
        if base[i] in _SWAP and base[j] in _SWAP:
            outs.add(base[:i] + _SWAP[base[i]] + base[i + 1 : j] + _SWAP[base[j]] + base[j + 1 :])
    return outs


def _pick(text):
    flat = re.sub(r"[^A-Z0-9\n ]", "", text.upper())
    toks = set(re.findall(r"[A-Z0-9]{11}", flat.replace(" ", "")))
    for m in re.finditer(
        r"IFSC?\s*(?:CODE)?\s*([A-Z0-9 ]{11,14})", flat
    ):  # tokens right after the label, tolerant of spaces
        toks.add(re.sub(r"\s", "", m.group(1))[:11])
    exact, repaired = [], []
    for t in toks:
        t11 = re.sub(r"[^A-Z0-9]", "", t)
        if len(t11) != 11:
            continue
        if validate_ifsc(t11)[0] and ifsc_exists(t11):
            exact.append(t11)
            continue
        hits = [c for c in _candidates(t11) if validate_ifsc(c)[0] and ifsc_exists(c)]
        if len(set(hits)) == 1 and t11[:3].isalpha():
            repaired.append(hits[0])  # unique dictionary hit only
    if exact:
        return sorted(exact)[0], "exact"
    if repaired:
        return sorted(repaired)[0], "repaired"
    # Read, but not in the RBI list (merged/retired bank, or a misread). Report it as format-only so the engine can say
    # "this code is not valid" instead of "unreadable".  Only for a token directly after an IFSC label, cleaned by position.
    for m in re.finditer(r"IFSC?\s*(?:CODE)?\s*([A-Z0-9 ]{11,14})", flat):
        t = re.sub(r"\s", "", m.group(1))[:11]
        if len(t) == 11:
            to_l = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"}
            c = "".join(to_l.get(ch, ch) for ch in t[:4]) + "0" + t[5:].replace("O", "0")
            if validate_ifsc(c)[0]:
                return c, "format-only"
    return None, "none"


def extract_ifsc(img_path):
    """(ifsc or None, how). Tesseract passes with early exit; RapidOCR as second engine. Accepts only values present in the RBI list."""
    im = Image.open(img_path) if isinstance(img_path, str) else img_path
    text, best = "", (None, "none")
    for p in _passes(im):
        for cfg in ("", "--psm 11"):
            text += "\n" + pytesseract.image_to_string(p, config=cfg)
        r = _pick(text)
        if r[0] and r[1] in ("exact", "repaired"):
            return r  # early exit: a dictionary-verified code was found
        if r[0]:
            best = r
    try:
        from ocrgst import rapid_text

        r2 = _pick(rapid_text(im))
        if r2[0] and r2[1] != "format-only":
            return r2[0], r2[1] + "+rapid"
    except Exception:
        pass
    return best
