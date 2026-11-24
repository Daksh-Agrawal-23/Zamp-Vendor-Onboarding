"""Verify a cheque image against the IFSC the vendor CLAIMED, using every signal on the leaf, not only the printed IFSC.

Why: on real cheques the IFSC is tiny print (often 2-3 mm tall), but the MICR band, the bank name and the branch name are large.
Signals (each independent):  IFSC text  |  MICR 9-digit code (city-bank-branch)  |  bank name  |  branch / city text.
Verdicts: confirmed (>=1 strong signal agrees, none contradict) | partial | contradicted (a strong signal names a different bank/branch)
          | unreadable (nothing usable).  A claimed code is never *accepted* from weak evidence alone.
Branch data comes from the public IFSC directory API (ifsc.razorpay.com, derived from RBI/NPCI lists), cached; offline -> bank-level checks only.
"""

import os, re, json, urllib.request
from functools import lru_cache
from rapidfuzz import fuzz
import numpy as np, cv2
from PIL import Image

_D = os.path.join(os.path.dirname(__file__), "data", "real")
_CACHE_P = os.path.join(_D, "ifsc_api_cache.json")
_BANKS = json.load(open(os.path.join(_D, "banks_meta.json")))
_NAMES = json.load(open(os.path.join(_D, "banknames.json")))
try:
    _CACHE = json.load(open(_CACHE_P))
except Exception:
    _CACHE = {}

# distinctive printed words per bank code (cheques print the brand, not the registered name)
_BRAND = {
    "UTIB": ["axis bank"],
    "ICIC": ["icici"],
    "HDFC": ["hdfc"],
    "SBIN": ["state bank of india", "sbi"],
    "PUNB": ["punjab national", "pnb"],
    "BARB": ["bank of baroda", "baroda"],
    "CNRB": ["canara"],
    "KKBK": ["kotak"],
    "YESB": ["yes bank"],
    "IDIB": ["indian bank"],
    "UBIN": ["union bank"],
    "BKID": ["bank of india"],
    "IOBA": ["indian overseas"],
    "CBIN": ["central bank"],
    "SYNB": ["syndicate"],
    "ORBC": ["oriental bank"],
    "IBKL": ["idbi"],
    "INDB": ["indusind"],
    "FDRL": ["federal bank"],
    "KARB": ["karnataka bank"],
    "MAHB": ["bank of maharashtra"],
    "UCBA": ["uco bank"],
    "ALLA": ["allahabad"],
    "ANDB": ["andhra bank"],
    "CORP": ["corporation bank"],
    "VIJB": ["vijaya bank"],
    "DENA": ["dena bank"],
    "PSIB": ["punjab & sind", "punjab and sind"],
    "RATN": ["rbl", "ratnakar"],
}


def bank_words(code4):
    w = list(_BRAND.get(code4, []))
    nm = (_NAMES.get(code4) or "").lower()
    if nm:
        w.append(re.sub(r"\b(ltd|limited|the|co|operative|coop)\b\.?", "", nm).strip())
    return [x for x in w if x]


def lookup(ifsc):
    """Branch record for an IFSC or None. Cached on disk; network optional."""
    ifsc = (ifsc or "").upper()
    if ifsc in _CACHE:
        return _CACHE[ifsc]
    try:
        r = json.load(urllib.request.urlopen(f"https://ifsc.razorpay.com/{ifsc}", timeout=6))
    except urllib.error.HTTPError as e:
        r = {"_missing": True} if e.code == 404 else None
    except Exception:
        r = None
    if r is not None:
        _CACHE[ifsc] = r
        try:
            json.dump(_CACHE, open(_CACHE_P, "w"))
        except Exception:
            pass
    return r


def micr_candidates(im):
    """9-digit runs from the MICR band (bottom strip of the leaf), by Tesseract (digits) and RapidOCR. Generic OCR reads the MICR font
    imperfectly, so every 9-digit window is kept and scored against the expected MICR later."""
    import pytesseract
    from ocrgst import rapid_text

    g = im.convert("L")
    w, h = g.size
    crop = g.crop((0, int(h * 0.70), w, h))
    if crop.width < 2200:
        crop = crop.resize((int(crop.width * 2), int(crop.height * 2)), Image.LANCZOS)
    found = []
    for cfg in (
        "--psm 7 -c tessedit_char_whitelist=0123456789 ",
        "--psm 6 -c tessedit_char_whitelist=0123456789 ",
    ):
        try:
            found += _runs(pytesseract.image_to_string(crop, config=cfg))
        except Exception:
            pass
    try:
        found += _runs(rapid_text(crop.convert("RGB")))
    except Exception:
        pass
    return found


def _runs(text):
    toks = re.findall(r"\d[\d ]{7,}\d|\d{9}", text.replace("O", "0").replace("o", "0"))
    out = []
    for t in toks:
        for part in re.split(r"\s{2,}", t):
            d = re.sub(r"\D", "", part)
            if len(d) == 9:
                out.append(d)
        d = re.sub(r"\D", "", t)
        # run-on strings: scan every 9-digit window; the caller scores them against the expected MICR
        for i in range(0, max(0, len(d) - 8)):
            out.append(d[i : i + 9])
    return out


def _micr_score(cands, expected):
    """best positional agreement between any 9-digit candidate and the expected MICR (0..9) and whether bank digits agree."""
    best, bank_ok = 0, False
    for c in cands:
        s = sum(a == b for a, b in zip(c, expected))
        best = max(best, s)
        if c[3:6] == expected[3:6] and c[:3] == expected[:3]:
            bank_ok = True
    return best, bank_ok


def verify(claimed_ifsc, im, ocr_text=None, ifsc_read=None, ifsc_how="none", micr=None):
    """Returns dict(verdict, signals, notes). `im` PIL image of the cheque; `ocr_text` full-page OCR text (optional, reused)."""
    claimed = (claimed_ifsc or "").upper()
    code4 = claimed[:4]
    rec = lookup(claimed)
    sig, notes = {}, []
    # 1. printed IFSC
    if ifsc_read and ifsc_how in ("exact", "repaired") or (ifsc_read and "rapid" in (ifsc_how or "")):
        sig["ifsc_text"] = "agree" if ifsc_read == claimed else "contradict"
        if ifsc_read != claimed:
            notes.append(f"cheque prints {ifsc_read}")
    # 2. MICR
    exp = (rec or {}).get("MICR") if rec and not rec.get("_missing") else None
    cands = micr if micr is not None else micr_candidates(im)
    if exp and len(str(exp)) == 9:
        best, bank_ok = _micr_score(cands, str(exp))
        if best >= 8:
            sig["micr"] = "agree"
        elif bank_ok or best >= 6:
            sig["micr"] = "bank_agrees"
        else:
            sig["micr"] = "none"
        # contradiction: a clean 9-digit read whose bank digits differ from the claimed bank
        bank_in_claim = {(_BANKS.get(code4) or {}).get("micr", "000000000")[3:6]}
        reads = [c for c in cands if c[:3].isdigit()]
        if sig["micr"] == "none" and cands:
            from collections import Counter

            top, n = Counter(c[3:6] for c in cands).most_common(1)[0]
            if (
                n >= 3
                and top not in bank_in_claim
                and any(_BANKS[b].get("micr", "")[3:6] == top for b in _BANKS if _BANKS[b].get("micr"))
            ):
                sig["micr"] = "bank_differs"
                notes.append(f"MICR band shows bank digits {top}")
    # 3. bank name
    if ocr_text:
        t = re.sub(r"[^a-z0-9& ]", " ", ocr_text.lower())
        t = re.sub(r"\s+", " ", t)
        words = bank_words(code4)
        hit = any(fuzz.partial_ratio(w, t) >= 88 and len(w) >= 4 for w in words) if words else False
        other = [b for b in _BRAND if b != code4 and any(w in t for w in _BRAND[b] if len(w) >= 5)]
        sig["bank_name"] = "agree" if hit else ("differs" if other and not hit else "none")
        if sig["bank_name"] == "differs":
            notes.append("cheque names " + other[0])
        # 4. branch / city
        if rec and not rec.get("_missing"):
            br = re.sub(r"[^a-z ]", " ", (rec.get("BRANCH") or "").lower()).strip()
            ce = (rec.get("CENTRE") or rec.get("CITY") or "").lower()
            bs = [x for x in re.split(r"[ ,]+", br) if len(x) >= 5 and x not in ("branch", "bank", "main")]
            if any(x in t for x in bs) or (ce and len(ce) >= 5 and ce in t):
                sig["branch"] = "agree"
    strong_ok = sig.get("ifsc_text") == "agree" or sig.get("micr") == "agree"
    contradict = (
        sig.get("ifsc_text") == "contradict"
        or sig.get("micr") == "bank_differs"
        or sig.get("bank_name") == "differs"
    )
    support = sum(1 for k, v in sig.items() if v in ("agree", "bank_agrees"))
    if contradict and not strong_ok:
        verdict = "contradicted"
    elif contradict and strong_ok:
        verdict = "conflicting"
    elif strong_ok and support >= 2:
        verdict = "confirmed"
    elif strong_ok or support >= 2:
        verdict = "partial"
    elif support == 1:
        verdict = "weak"
    else:
        verdict = "unreadable"
    return dict(
        verdict=verdict, signals=sig, notes=notes, micr_read=sorted(set(cands))[:6], expected_micr=exp
    )


def account_candidates(text):
    """(anchored, loose): digit runs right after an A/C label, and any other long run (may be MICR/cheque numbers)."""
    t = (text or "").upper()
    anch, loose = [], []
    for m in re.finditer(
        r"(?:A\s*/?\s*C|ACCOUNT|AC)\s*(?:NO|NUMBER|NUM)?\.?\s*[:\-]?\s*([A-Z]{0,3}\s?[0-9][0-9 ]{7,22})", t
    ):
        d = re.sub(r"\D", "", m.group(1))
        if 9 <= len(d) <= 18:
            anch.append(d)
    for m in re.finditer(r"(?<![0-9])([0-9][0-9 ]{9,22}[0-9])(?![0-9])", t):
        d = re.sub(r"\D", "", m.group(1))
        if 11 <= len(d) <= 18:
            loose.append(d)
    return list(dict.fromkeys(anch)), list(dict.fromkeys(loose))


def account_match(claimed, cands):
    """cands = (anchored, loose). 'match' if the declared account appears (<=1 wrong digit); 'differs' only if an A/C-labelled read of the same
    length disagrees in 3+ digits; otherwise 'unread' (OCR failure is never held against the vendor)."""
    c = re.sub(r"\D", "", claimed or "")
    anch, loose = cands if cands else ([], [])
    if not c:
        return "unread"
    best = 0
    same_len = False
    for d in anch + loose:
        if c in d or (d in c and len(d) >= 9):
            return "match"
        if len(d) == len(c):
            s = sum(a == b for a, b in zip(c, d))
            if s >= len(c) - 1:
                return "match"
            if d in anch:
                same_len = True
                best = max(best, s)
    if same_len and best <= len(c) - 3:
        return "differs"
    return "unread"
