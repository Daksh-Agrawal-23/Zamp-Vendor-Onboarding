"""Deterministic identifier validators for vendor onboarding.

Each validator returns (ok: bool, reason: str). No network, no model.
"""

import re
from difflib import SequenceMatcher

B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

GST_STATE_CODES = {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}
PAN_4TH = set("ABCFGHJLPT")  # entity type letter
PAN_ENTITY = {
    "A": "Association of persons",
    "B": "Body of individuals",
    "C": "Company",
    "F": "Firm / LLP",
    "G": "Government",
    "H": "Hindu undivided family",
    "J": "Artificial juridical person",
    "L": "Local authority",
    "P": "Individual",
    "T": "Trust",
}
PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHJLPT][A-Z]\d{4}[A-Z]$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def gstin_check_char(first14: str) -> str:
    """GSTIN check character: mod-36, factor alternates 1,2 from the left."""
    total = 0
    for i, ch in enumerate(first14):
        d = B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += d // 36 + d % 36
    return B36[(36 - total % 36) % 36]


def validate_gstin(g: str):
    g = (g or "").strip().upper()
    if not GSTIN_RE.match(g):
        return False, "GSTIN structure invalid (expected 15 chars: 2 digits, PAN, entity no., Z, check)"
    if g[:2] not in GST_STATE_CODES:
        return False, f"unknown GST state code {g[:2]}"
    if gstin_check_char(g[:14]) != g[14]:
        return False, "GSTIN check character does not match"
    return True, "ok"


def validate_pan(p: str):
    p = (p or "").strip().upper()
    if not PAN_RE.match(p):
        return False, "PAN structure invalid (expected AAAAA9999A with valid 4th letter)"
    return True, "ok"


def pan_from_gstin(g: str) -> str:
    return (g or "").strip().upper()[2:12]


def gstin_pan_consistent(g: str, p: str):
    return pan_from_gstin(g) == (p or "").strip().upper()


BIZ_WORDS = {
    "TRADERS",
    "ENTERPRISES",
    "ENTERPRISE",
    "INDUSTRIES",
    "ELECTRONICS",
    "TRADING",
    "SERVICES",
    "STORES",
    "AGENCIES",
    "TOURS",
    "WORKS",
    "MOTORS",
    "FOODS",
    "SOLUTIONS",
    "CONSTRUCTION",
    "FACTORY",
    "COMPANY",
    "ASSOCIATES",
    "BROTHERS",
    "MART",
}


def pan_name_hint(p: str, legal_name: str):
    """Soft check of PAN char 5 against the name. Real-data calibrated (see eval_real.py):
    - entity PANs (C, F, T, A, B, G, L, J): initial of the first word, with or without a leading THE/M/S;
    - personal PANs (P, H): only checked when the name looks like a person (a proprietor's PAN sits under a
      business name, so a trade name proves nothing); accepts the first or last word's initial.
    Returns True/False, or None when the rule does not apply."""
    p = (p or "").strip().upper()
    words = re.sub(r"[^A-Z ]", " ", (legal_name or "").upper()).split()
    if len(p) != 10 or not words:
        return None
    core = [w for w in words if w not in {"M", "S", "MS", "THE"}] or words
    co_words = {"PRIVATE", "PVT", "LIMITED", "LTD"}
    if p[3] in "PH" and (co_words & set(words) or "LLP" in words):
        return False  # an individual's PAN cannot belong to a company or LLP
    if p[3] == "C" and "LLP" in words:
        return False  # a company PAN cannot belong to an LLP
    if p[3] == "F" and (co_words & set(words)):
        return False  # a firm/LLP PAN cannot belong to a company
    if p[3] in "PH":
        if any(w in BIZ_WORDS for w in words):
            return None
        return p[4] in {core[0][0], core[-1][0]}
    return p[4] in {core[0][0], words[0][0]}


def validate_ifsc(i: str):
    i = (i or "").strip().upper()
    if not IFSC_RE.match(i):
        return False, "IFSC invalid (4 letters, 0, 6 alphanumerics)"
    return True, "ok"


EIN_PREFIXES = {
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "20",
    "21",
    "22",
    "23",
    "24",
    "25",
    "26",
    "27",
    "30",
    "31",
    "32",
    "33",
    "34",
    "35",
    "36",
    "37",
    "38",
    "39",
    "40",
    "41",
    "42",
    "43",
    "44",
    "45",
    "46",
    "47",
    "48",
    "50",
    "51",
    "52",
    "53",
    "54",
    "55",
    "56",
    "57",
    "58",
    "59",
    "60",
    "61",
    "62",
    "63",
    "64",
    "65",
    "66",
    "67",
    "68",
    "71",
    "72",
    "73",
    "74",
    "75",
    "76",
    "77",
    "80",
    "81",
    "82",
    "83",
    "84",
    "85",
    "86",
    "87",
    "88",
    "90",
    "91",
    "92",
    "93",
    "94",
    "95",
    "98",
    "99",
}
EIN_RE = re.compile(r"^(\d{2})-(\d{7})$")


def validate_ein(e: str):
    m = EIN_RE.match((e or "").strip())
    if not m:
        return False, "EIN must look like XX-XXXXXXX"
    if m.group(1) not in EIN_PREFIXES:
        return False, f"EIN prefix {m.group(1)} is not assigned"
    if len(set(m.group(1) + m.group(2))) == 1:
        return False, "EIN is a repeated digit"
    return True, "ok"


_VAT_W = [8, 7, 6, 5, 4, 3, 2]


def validate_uk_vat(v: str):
    v = re.sub(r"[\s-]", "", (v or "").upper())
    if v.startswith("GB"):
        v = v[2:]
    if not re.fullmatch(r"\d{9}|\d{12}", v):
        return False, "UK VAT must be 9 or 12 digits"
    d = [int(c) for c in v[:9]]
    s = sum(x * w for x, w in zip(d[:7], _VAT_W))
    total = s + d[7] * 10 + d[8]  # weights 8..2, 10, 1
    if total % 97 in (0, 42):  # 0 = original algorithm, 42 = post-2010 algorithm
        return True, "ok"
    return False, "UK VAT mod-97 check failed"


LEGAL_SUFFIXES = {
    "PVT",
    "PRIVATE",
    "LTD",
    "LIMITED",
    "LLP",
    "LLC",
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "PLC",
    "LP",
    "OPC",
    "M/S",
    "MS",
    "THE",
    "AND",
    "&",
}


import unicodedata

_HOMOGLYPH = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "І": "I",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "Ѕ": "S",
        "Α": "A",
        "Β": "B",
        "Ε": "E",
        "Ζ": "Z",
        "Η": "H",
        "Ι": "I",
        "Κ": "K",
        "Μ": "M",
        "Ν": "N",
        "Ο": "O",
        "Ρ": "P",
        "Τ": "T",
        "Χ": "X",
        "а": "a",
        "с": "c",
        "е": "e",
        "о": "o",
        "р": "p",
        "х": "x",
        "у": "y",
        "і": "i",
        "ѕ": "s",
        "ο": "o",
    }
)
_HOMOGLYPH_SRC = set("АВСЕНІКМОРТХУЅΑΒΕΖΗΙΚΜΝΟΡΤΧасеорхуіѕο")
_DEVA = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "f",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "ं": "n",
    "ः": "h",
    "ँ": "n",
    "ा": "a",
    "ि": "i",
    "ी": "ee",
    "ु": "u",
    "ू": "oo",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "्": "",
    "़": "",
}


def fold_script(s: str) -> str:
    """Make names comparable across look-alike scripts: NFKC, strip accents, map Cyrillic/Greek homoglyphs to Latin, rough Devanagari -> Latin.
    Transliterated matches are capped at 'review' by the callers (never a clean pass)."""
    s = unicodedata.normalize("NFKC", s or "").translate(_HOMOGLYPH)
    if any("\u0900" <= ch <= "\u097f" for ch in s):
        out, prev_cons = [], False
        for ch in s:
            m = _DEVA.get(ch)
            if m is None:
                out.append(ch)
                prev_cons = False
                continue
            is_cons = ch in "कखगघचछजझटठडढणतथदधनपफबभमयरलवशषसह"
            if prev_cons and ch not in "ािीुूेैोौ्ंःँ" and is_cons:
                out.append("a")  # inherent 'a' between consonants
            out.append(m)
            prev_cons = is_cons
        s = "".join(out)
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalise_name(n: str) -> str:
    n = fold_script(n or "").upper().replace("&", " AND ")
    n = re.sub(r"^\s*(M\s*/\s*S\.?|MESSRS\.?)\s+", "", n)  # 'M/S' prefix
    n = re.sub(
        r"\(\s*P\s*\)\s*LTD\b\.?|\bP\b\.?\s*LTD\b", "PRIVATE LIMITED", n
    )  # 'P LTD' / 'P. LTD' (766 real names)
    n = re.sub(r"[^\w\s]", " ", n)
    toks = [t for t in n.split() if t not in LEGAL_SUFFIXES]
    return " ".join(toks) or " ".join(n.split())  # a name made only of suffix words keeps its tokens


# ---- Indian-name aware matching -------------------------------------------------------------------------------------
_HONOR = {
    "MR",
    "MRS",
    "MS",
    "MISS",
    "SHRI",
    "SRI",
    "SHREE",
    "SMT",
    "SHRIMATI",
    "DR",
    "PROF",
    "LATE",
    "PROP",
    "PROPRIETOR",
    "PROPRIETRESS",
    "PROPRIETORSHIP",
    "OF",
    "S/O",
    "D/O",
    "W/O",
}
_CANON = {
    "MOHD": "MOHAMMAD",
    "MD": "MOHAMMAD",
    "MOHAMED": "MOHAMMAD",
    "MOHAMMED": "MOHAMMAD",
    "MUHAMMAD": "MOHAMMAD",
    "MOHAMAD": "MOHAMMAD",
    "MUHAMMED": "MOHAMMAD",
    "ENGG": "ENGINEERING",
    "ENGRS": "ENGINEERS",
    "INDS": "INDUSTRIES",
    "INDL": "INDUSTRIAL",
    "INDUSTRY": "INDUSTRIES",
    "CORPN": "CORPORATION",
    "BROS": "BROTHERS",
    "MFG": "MANUFACTURING",
    "MFRS": "MANUFACTURERS",
    "TRDG": "TRADING",
    "ENT": "ENTERPRISES",
    "ENTP": "ENTERPRISES",
    "ENTERPRISE": "ENTERPRISES",
    "SVCS": "SERVICES",
    "SERVICE": "SERVICES",
    "INTL": "INTERNATIONAL",
    "TRADERS": "TRADERS",
    "TRADER": "TRADERS",
    "ASSOC": "ASSOCIATES",
    "TECH": "TECHNOLOGIES",
    "TECHNOLOGY": "TECHNOLOGIES",
    "SOLN": "SOLUTIONS",
    "SOLUTION": "SOLUTIONS",
    "SYS": "SYSTEMS",
    "SYSTEM": "SYSTEMS",
    "CONST": "CONSTRUCTION",
    "CONSTRUCTIONS": "CONSTRUCTION",
    "AGENCY": "AGENCIES",
    "STORE": "STORES",
    "WORK": "WORKS",
    "LAKSHMI": "LAXMI",
    "LAKSMI": "LAXMI",
    "LAXMEE": "LAXMI",
    "KRIPA": "KRUPA",
    "POOJA": "PUJA",
    "PUJA": "PUJA",
    "AARTI": "ARTI",
    "AARATI": "ARTI",
    "RAFIQ": "RAFIQUE",
    "RAFEEK": "RAFIQUE",
    "LEYLAND": "LAYLAND",
    "LABS": "LABORATORIES",
    "LAB": "LABORATORIES",
    "LABORATORY": "LABORATORIES",
    "KUMAR": "KUMAR",
    "KR": "KUMAR",
    "CHAND": "CHAND",
    "CHANDRA": "CHANDRA",
}
_GENERIC_MIDDLE = {
    "KUMAR",
    "KUMARI",
    "DEVI",
    "LAL",
    "CHAND",
    "CHANDRA",
    "PRASAD",
    "NATH",
    "SINGH",
    "RAM",
    "KAUR",
    "BEN",
    "BHAI",
    "RAO",
    "REDDY",
}  # frequent given/middle tokens


def _tokens(n):
    n = fold_script(n or "").upper().replace("&", " AND ")
    n = re.sub(r"^\s*(M\s*/\s*S\.?|MESSRS\.?)\s+", "", n)
    n = re.sub(r"\(\s*P\s*\)\s*LTD\b\.?|\bP\b\.?\s*LTD\b", "PRIVATE LIMITED", n)
    n = re.sub(
        r"\(\s*(?:PROP|PROPRIETOR|PARTNER|DIRECTOR)\b[^)]*\)", " ", n
    )  # '(Prop. Ramesh Sharma)' = who owns it, not part of the trade name
    n = re.sub(r"\b[SDW]\s*/\s*O\b.*$", "", n)  # 'S/O father name' tail
    n = re.sub(r"\bTRADING\s+AS\b|\bT/A\b|\bPROP(?:RIETOR)?\.?\s+(?:OF|:)?", " ", n)
    n = re.sub(
        r"\(\s*(?:FORMERLY|FORMERLY KNOWN AS|FKA|F/K/A|EARLIER|NOW)\b[^)]*\)", " ", n
    )  # '(formerly X)' is history, not the name
    n = re.sub(r"[^\w\s]", " ", n)
    out = []
    for t in n.split():
        if t in LEGAL_SUFFIXES or t in _HONOR:
            continue
        out.append(_CANON.get(t, t))
    return out


def _joined(toks):
    return re.sub(
        r"(.)\1+",
        r"\1",
        "".join(toks).replace("KSH", "X").replace("AA", "A").replace("OO", "U").replace("EE", "I"),
    )


def _tok_sim(x, y):
    """similarity of two tokens 0..1; initials count 0.75; short tokens (<=4) must be equal or initial."""
    if x == y:
        return 1.0
    if len(x) == 1 or len(y) == 1:
        return 0.92 if x[0] == y[0] else 0.0
    r = SequenceMatcher(None, x, y).ratio()
    if min(len(x), len(y)) <= 4:
        return 0.0 if r < 0.95 else r
    return (
        r if r >= 0.88 else 0.0
    )  # one differing letter in a 5-6 letter name (Ramesh/Rakesh, Singh/Sinha) is a different person


def name_match(a, b):
    """(score 0-100, why). Token-level: honorifics/abbreviations normalised, initials expanded, extra middle names tolerated, acronyms flagged for review,
    and a differing distinctive token is a conflict instead of a 'close enough' character ratio."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0, "empty"
    if ta == tb:
        return 100, "same tokens"
    if sorted(ta) == sorted(tb):
        return 97, "same tokens, different order"
    if len(ta) != len(tb) and len(_joined(ta)) >= 6 and _joined(ta) == _joined(tb):
        return 95, "same name, spaced differently (Sairam / Sai Ram)"
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    used, sims = set(), []
    for s in short:  # greedy best-first alignment
        best, bj = 0.0, None
        for j, l in enumerate(long_):
            if j in used:
                continue
            v = _tok_sim(s, l)
            if v > best:
                best, bj = v, j
        if bj is not None and best > 0:
            used.add(bj)
        sims.append(best)
    cover = sum(sims) / len(short)
    if len(short) >= 2 and any(len(s) == 1 for s in short) and cover >= 0.9:
        cover = min(cover, 0.84)  # an initial standing for a name is a review, never a clean pass
    unmatched_short = [s for s, v in zip(short, sims) if v == 0.0]
    extra = [l for j, l in enumerate(long_) if j not in used]
    if not unmatched_short:
        pen = 0.0
        if extra:
            distinctive = [e for e in extra if e not in _GENERIC_MIDDLE and len(e) > 2]
            pen = 0.05 * len([e for e in extra if e in _GENERIC_MIDDLE or len(e) <= 2]) + 0.18 * len(
                distinctive
            )
            if len(short) == 1:
                pen += 0.15  # one word vs a longer name is weak evidence
        sc = round(100 * max(0.0, cover - pen))
        return sc, f"{len(short)} token(s) matched, extra {extra}"
    # acronym: TCS ~ Tata Consultancy Services
    ac = "".join(t[0] for t in long_)
    raw = [
        t
        for t in re.sub(r"[^\w\s]", " ", fold_script(b if long_ is tb else a).upper()).split()
        if t not in _HONOR
    ]
    ac2 = "".join(t[0] for t in raw)
    if len(short) == 1 and len(short[0]) >= 2 and short[0] == ac2 and short[0] != ac:
        return 78, "acronym of the other name incl. 'Limited' (needs review)"
    if len(short) == 1 and len(short[0]) >= 2 and short[0] == ac:
        return 78, "acronym of the other name (needs review)"
    sc = round(
        100 * cover * (len(short) - len(unmatched_short)) / len(short) * (0.6 if len(unmatched_short) else 1)
    )
    return min(sc, 59 if len(unmatched_short) * 2 >= len(short) else 70), f"unmatched {unmatched_short}"


def legal_form(name):
    """'pvt' (private limited), 'public' (limited), 'llp', or None when the name states no company form."""
    n = " " + re.sub(r"[^A-Z ]", " ", fold_script(name or "").upper().replace("(P)", " PRIVATE ")) + " "
    n = re.sub(r"\s+", " ", n)
    if " LLP " in n:
        return "llp"
    if re.search(r" (PRIVATE|PVT) (LIMITED|LTD) | P LTD ", n) or " PRIVATE " in n:
        return "pvt"
    if re.search(r" (LIMITED|LTD) ", n):
        return "public"
    return None


def has_homoglyphs(s: str) -> bool:
    """Latin letters mixed with Cyrillic/Greek look-alikes inside one name (a classic duplicate/fraud trick)."""
    s = s or ""
    return any(re.match(r"[A-Za-z]", c) for c in s) and any(c in _HOMOGLYPH_SRC for c in s)


def non_latin(s: str) -> bool:
    return any("\u0900" <= c <= "\u097f" for c in (s or ""))


def name_score(a: str, b: str) -> int:
    """0-100. Legal-suffix/honorific/abbreviation-insensitive, order-insensitive, initial-aware (see name_match).
    A match that relied on transliterating Devanagari is capped at 84 (review), never a clean pass."""
    x, y = normalise_name(a), normalise_name(b)
    if not x or not y:
        return 0
    s = name_match(a, b)[0]
    return min(s, 84) if (non_latin(a) or non_latin(b)) else s


def name_in_text(name, text):
    """(percent, why): share of the declared name's distinctive words found in OCR text (fuzzy per word, initials ignored). Words, not characters,
    so 'Gupta' alone cannot satisfy 'Gupta Traders'."""
    toks = [t for t in _tokens(name) if len(t) > 1] or _tokens(name)
    words = set(re.findall(r"[A-Z]{2,}", re.sub(r"[^A-Z\s]", " ", (text or "").upper())))
    if not toks:
        return 0, "empty"
    got = 0
    for t in toks:
        if t in words or any(
            len(w) >= 4 and len(t) >= 4 and SequenceMatcher(None, t, _CANON.get(w, w)).ratio() >= 0.88
            for w in words
        ):
            got += 1
    return round(100 * got / len(toks)), f"{got}/{len(toks)} words"


def name_band(score: int) -> str:
    return "pass" if score >= 85 else "review" if score >= 60 else "conflict"


# ---- CIN (Indian company registration number, 21 chars) -------------------
# L/U (listed/unlisted) + 5-digit NIC + 2-letter state + 4-digit year
# + 3-letter class (PLC, PTC, GOI, NPL, FTC, OPC, SGC, ULL, ULT, FLC) + 6 digits
CIN_RE = re.compile(r"^([LU])(\d{5})([A-Z]{2})(\d{4})([A-Z]{3})(\d{6})$")
CIN_CLASSES = {
    "PTC",
    "PLC",
    "GOI",
    "NPL",
    "FTC",
    "OPC",
    "SGC",
    "ULL",
    "ULT",
    "FLC",
    "GAP",
    "GAT",
    "PLN",
    "SFC",
}  # all 14 seen in 854k real MCA CINs (PLN = Nidhi)


def parse_cin(c: str):
    m = CIN_RE.match((c or "").strip().upper())
    if not m:
        return None
    return dict(
        listed=m.group(1) == "L",
        nic=m.group(2),
        state=m.group(3),
        year=int(m.group(4)),
        klass=m.group(5),
        serial=m.group(6),
    )


def validate_cin(c: str, today_year: int = 2026):
    p = parse_cin(c)
    if not p:
        return False, "CIN structure invalid (21 chars: L/U, NIC, state, year, class, serial)"
    if p["klass"] not in CIN_CLASSES:
        return False, f"unknown CIN company class {p['klass']}"
    if not (1850 <= p["year"] <= today_year):
        return False, f"CIN incorporation year {p['year']} is impossible"
    return True, "ok"


def cin_name_consistent(c: str, legal_name: str):
    """Soft check, calibrated on 824k real MCA records.
    Only the reliable direction is used: a name saying 'Private Limited' should not carry a public-company class
    (99.8% hold). The reverse is NOT checked: 37k real private companies are named '... Limited'
    (Farmer Producer Companies, Section 8, Nidhi), so it would wrongly flag genuine vendors."""
    p = parse_cin(c)
    n = normalise_suffix_text(legal_name)
    if not p or "PRIVATE" not in n:
        return None
    return p["klass"] not in {"PLC", "GOI", "NPL", "ULL", "FLC", "PLN"}


def normalise_suffix_text(n: str) -> str:
    n = (n or "").upper()
    n = re.sub(r"\bPVT\b\.?", "PRIVATE", n)
    n = re.sub(r"\bLTD\b\.?", "LIMITED", n)
    return re.sub(r"[^A-Z ]", "", n).strip()


# ---- near-miss repair: suggest a corrected GSTIN for look-alike typos -------
_CONFUSABLE = {
    "I": "1",
    "1": "IZ",
    "O": "0",
    "0": "O",
    "S": "5",
    "5": "S",
    "B": "8",
    "8": "B",
    "Z": "21",
    "2": "Z",
}


_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6", "T": "7"}
_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}


def canonicalise_gstin(g: str) -> str:
    """Position-aware look-alike repair: GSTIN layout fixes which positions are digits/letters
    (2 digits | 5 letters | 4 digits | 1 letter | 1 alnum | 'Z' | check). Deterministic, so it adds no ambiguity;
    the checksum still has to pass before the result is used."""
    g = (g or "").strip().upper()
    if len(g) != 15:
        return g
    out = []
    for i, ch in enumerate(g):
        if i in (0, 1, 7, 8, 9, 10):
            out.append(_TO_DIGIT.get(ch, ch))
        elif i in (2, 3, 4, 5, 6, 11):
            out.append(_TO_LETTER.get(ch, ch))
        elif i == 13:
            out.append("Z" if ch in "2" else ch)
        else:
            out.append(ch)
    return "".join(out)


def suggest_gstin_fix(g: str):
    """If a GSTIN fails only its check, try single look-alike swaps (I/1, O/0, S/5, B/8, Z/2).
    Returns the unique valid candidate, else None (ambiguous or no fix)."""
    g = (g or "").strip().upper()
    if len(g) != 15 or validate_gstin(g)[0]:
        return None
    canon = canonicalise_gstin(g)
    if canon != g and validate_gstin(canon)[0]:
        return canon
    hits = {
        g[:i] + alt + g[i + 1 :] for i, ch in enumerate(g) if ch in _CONFUSABLE for alt in _CONFUSABLE[ch]
    }
    ok = [h for h in hits if validate_gstin(h)[0]]
    return ok[0] if len(ok) == 1 else None


# ---- state consistency (real-data calibrated) -------------------------------
GST2ISO = {
    "01": "JK",
    "02": "HP",
    "03": "PB",
    "04": "CH",
    "05": "UT",
    "06": "HR",
    "07": "DL",
    "08": "RJ",
    "09": "UP",
    "10": "BR",
    "11": "SK",
    "12": "AR",
    "13": "NL",
    "14": "MN",
    "15": "MZ",
    "16": "TR",
    "17": "ML",
    "18": "AS",
    "19": "WB",
    "20": "JH",
    "21": "OR",
    "22": "CT",
    "23": "MP",
    "24": "GJ",
    "25": "DD",
    "26": "DN",
    "27": "MH",
    "28": "AP",
    "29": "KA",
    "30": "GA",
    "31": "LD",
    "32": "KL",
    "33": "TN",
    "34": "PY",
    "35": "AN",
    "36": "TG",
    "37": "AP",
    "38": "LA",
}
_ALIAS = {
    "OR": {"OR", "OD"},
    "CT": {"CT", "CG"},
    "UT": {"UT", "UK"},
    "DD": {"DD", "DN", "DH"},
    "DN": {"DD", "DN", "DH"},
    "AP": {"AP"},
    "TG": {"TG", "TS"},
    "JK": {"JK", "LA"},
    "LA": {"LA", "JK"},
}
# CIN's 2 letters are Registrar-of-Companies jurisdiction codes, some historical (PN = Pune RoC, TZ = old Tamil Nadu)
CIN_ROC2ISO = {
    "PN": "MH",
    "MH": "MH",
    "ME": "MH",
    "MR": "MH",
    "KA": "KA",
    "DL": "DL",
    "DC": "DL",
    "TN": "TN",
    "TZ": "TN",
    "GJ": "GJ",
    "HR": "HR",
    "UP": "UP",
    "UW": "UP",
    "TG": "TG",
    "WB": "WB",
    "WR": "WB",
    "RJ": "RJ",
    "PB": "PB",
    "MP": "MP",
    "AP": "AP",
    "KL": "KL",
    "OR": "OR",
    "CT": "CT",
    "JH": "JH",
    "BR": "BR",
    "UR": "UT",
    "UT": "UT",
    "CH": "CH",
    "GA": "GA",
    "HP": "HP",
    "JK": "JK",
    "AS": "AS",
    "DN": "DN",
    "DD": "DD",
    "PY": "PY",
}


STATE_NAME2ISO = {
    "JAMMU AND KASHMIR": "JK",
    "HIMACHAL PRADESH": "HP",
    "PUNJAB": "PB",
    "CHANDIGARH": "CH",
    "UTTARAKHAND": "UT",
    "HARYANA": "HR",
    "DELHI": "DL",
    "RAJASTHAN": "RJ",
    "UTTAR PRADESH": "UP",
    "BIHAR": "BR",
    "SIKKIM": "SK",
    "ARUNACHAL PRADESH": "AR",
    "NAGALAND": "NL",
    "MANIPUR": "MN",
    "MIZORAM": "MZ",
    "TRIPURA": "TR",
    "MEGHALAYA": "ML",
    "ASSAM": "AS",
    "WEST BENGAL": "WB",
    "JHARKHAND": "JH",
    "ODISHA": "OR",
    "CHHATTISGARH": "CT",
    "MADHYA PRADESH": "MP",
    "GUJARAT": "GJ",
    "MAHARASHTRA": "MH",
    "ANDHRA PRADESH": "AP",
    "KARNATAKA": "KA",
    "GOA": "GA",
    "KERALA": "KL",
    "TAMIL NADU": "TN",
    "PUDUCHERRY": "PY",
    "TELANGANA": "TG",
    "LADAKH": "LA",
    "LAKSHADWEEP": "LD",
    "ANDAMAN AND NICOBAR ISLANDS": "AN",
}


def _region_ok(iso, region):
    region = (region or "").upper().replace("IN-", "").replace("&", "AND").strip()
    region = STATE_NAME2ISO.get(region, region)
    return bool(iso) and (region == iso or region in _ALIAS.get(iso, ()))


def gstin_state_matches(gstin: str, region: str):
    """GSTIN state code vs address region (ISO 3166-2:IN suffix). A flag, not a hard block."""
    return _region_ok(GST2ISO.get((gstin or "")[:2]), region)


def cin_state_matches(cin: str, region: str):
    """CIN jurisdiction vs address region. INFORMATIONAL only: companies relocate and RoC codes are historical."""
    p = parse_cin(cin)
    return bool(p) and _region_ok(CIN_ROC2ISO.get(p["state"]), region)


# ---- IFSC existence against the RBI-derived code list (Razorpay IFSC-list.json) -------------
import json as _json, os as _os

_IFSC_PATH = _os.path.join(_os.path.dirname(__file__), "data", "real", "ifsc_list.json")
_IFSC = None


def ifsc_exists(i: str):
    """True/False if the IFSC is/isn't in the RBI-derived list; None if the list is unavailable."""
    global _IFSC
    if _IFSC is None:
        try:
            raw = _json.load(open(_IFSC_PATH))
            _IFSC = {
                k: {str(x).upper().zfill(6) if isinstance(x, int) else str(x).upper() for x in v}
                for k, v in raw.items()
            }
        except OSError:
            _IFSC = {}
    if not _IFSC:
        return None
    i = (i or "").strip().upper()
    return len(i) == 11 and i[:4] in _IFSC and i[5:] in _IFSC[i[:4]]


def ifsc_status(i: str):
    """Granular IFSC outcome so the vendor message can be specific.
    ok | bad_format | unknown_bank | retired_bank (bank merged: code survives with no live branches) | unknown_branch | unchecked
    """
    ok, _ = validate_ifsc(i)
    if not ok:
        return "bad_format"
    if ifsc_exists("SBIN0001234") is None:
        return "unchecked"
    i = i.strip().upper()
    ifsc_exists(i)
    branches = _IFSC.get(i[:4])
    if branches is None:
        return "unknown_bank"
    live = [b for b in branches if b != "00RTGS" and not b.isalpha()]
    if len(live) == 0:
        return "retired_bank"
    return "ok" if i[5:] in branches else "unknown_branch"


# ---- LLP identification number: AAA-1234 ------------------------------------
LLPIN_RE = re.compile(r"^[A-Z]{3}-\d{4}$")


def validate_llpin(x: str):
    return (
        (True, "ok")
        if LLPIN_RE.match((x or "").strip().upper())
        else (False, "LLPIN must look like AAA-1234")
    )


def cin_year_matches_incorporation(cin: str, incorporation_date: str):
    """CIN embeds the incorporation year; in 99.97% of 850k real records it equals the registration year.
    A mismatch is a strong typo/forgery signal. incorporation_date: YYYY-MM-DD or DD/MM/YYYY."""
    p = parse_cin(cin)
    m = re.search(r"(\d{4})", incorporation_date or "")
    return None if not (p and m) else p["year"] == int(m.group(1))
