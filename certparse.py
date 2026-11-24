"""Field parsers for Indian registration documents (GST REG-06, PAN card, Udyam certificate) over OCR/text-layer output.
Layout-tolerant: a value may follow its label on the same line or on the next non-empty line; row numbers ('1.') and punctuation are ignored.
"""

import re

_NOISE = re.compile(r"^[\W_]+$")


def _clean(v):
    v = re.sub(r"\s+", " ", (v or "")).strip(" :-|_.,;")
    return v


def _after(label_re, text, stop_re=None, max_len=90, lines_ahead=2, allow_before=False):
    """Value that follows a label: rest of the same line, else the next non-empty line(s). Stops at the next known label."""
    lines = [l for l in text.splitlines()]
    for i, l in enumerate(lines):
        m = re.search(label_re, l, re.I)
        if not m:
            continue
        rest = _clean(l[m.end() :])
        if len(re.sub(r"[^A-Za-z]", "", rest)) >= 3 and not (stop_re and re.match(stop_re, rest, re.I)):
            return rest[:max_len]
        for j in range(i + 1, min(len(lines), i + 1 + lines_ahead + 2)):
            nxt = _clean(lines[j])
            if not nxt or _NOISE.match(nxt):
                continue
            if stop_re and re.match(stop_re, nxt, re.I):
                break
            if len(re.sub(r"[^A-Za-z0-9]", "", nxt)) >= 3:
                return nxt[:max_len]
        if allow_before:  # table cells are often OCR'd with the value ABOVE its label
            for j in range(i - 1, max(-1, i - 3), -1):
                prv = _clean(lines[j])
                if not prv:
                    continue
                if re.search(
                    r"registration number|government|form gst|certificate|\[see rule|^\d\s*[.)]|:\s*\d{2}[A-Z]{5}",
                    prv,
                    re.I,
                ) or (stop_re and re.match(stop_re, prv, re.I)):
                    break
                if len(re.sub(r"[^A-Za-z]", "", prv)) >= 3:
                    return prv[:max_len]
    return None


_GST_LABELS = r"(?:\d\s*[.)]\s*)?(?:legal\s*name|trade\s*name|constitution|address|date\s+of|period|type\s+of|particulars|name\s+of)"


def parse_reg06(text):
    t = text or ""
    out = {}
    ln = _after(
        r"(?:\d\s*[.)]\s*)?legal\s*name(?:\s*of\s*(?:the\s*)?business)?\s*[:\-]?",
        t,
        stop_re=_GST_LABELS,
        allow_before=True,
    )
    if ln:
        out["legal_name"] = ln
    tn = _after(r"(?:\d\s*[.)]\s*)?trade\s*name(?:\s*,?\s*if\s*any)?\s*[:\-]?", t, stop_re=_GST_LABELS)
    if tn:
        out["trade_name"] = tn
    cb = _after(r"constitution\s*of\s*business\s*[:\-]?", t, stop_re=_GST_LABELS)
    if cb:
        out["constitution"] = cb
    m = re.search(
        r"\b(regular|composition|casual\s+taxable|input\s+service\s+distributor|sez|non[- ]resident|tds|tcs)\b",
        t,
        re.I,
    )
    if m:
        out["registration_type"] = m.group(1).title()
    out["composition"] = bool(re.search(r"composition", t, re.I))
    m = re.search(r"valid(?:ity)?[^\n]{0,40}?to\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})", t, re.I)
    if m:
        out["valid_to"] = m.group(1)
    out["is_reg06"] = bool(re.search(r"registration\s+certificate|reg-?06", t, re.I))
    return out


def parse_pan_card(text):
    """Name printed on a PAN card (the line after 'Name', not 'Father's Name')."""
    t = text or ""
    lines = [l for l in t.splitlines()]
    for i, l in enumerate(lines):
        if re.search(r"father|पिता", l, re.I):
            continue
        if re.fullmatch(
            r"\s*(?:\d\s*[.)]\s*)?(?:name|नाम)\s*[/:]?\s*(?:name)?\s*[:\-]?\s*", l, re.I
        ) or re.match(r"\s*name\s*[:\-]\s*\S", l, re.I):
            m = re.match(r"\s*name\s*[:\-]\s*(.+)", l, re.I)
            if m and len(m.group(1)) >= 3:
                return _clean(m.group(1))[:80]
            for j in range(i + 1, min(len(lines), i + 4)):
                nxt = _clean(lines[j])
                if re.search(r"father|date of birth|signature|जन्म", nxt, re.I):
                    break
                if len(re.sub(r"[^A-Za-z]", "", nxt)) >= 3 and not re.search(
                    r"permanent|income|govt", nxt, re.I
                ):
                    return nxt[:80]
    return None


UDYAM_RE = re.compile(r"UDYAM\s*-?\s*([A-Z]{2})\s*-?\s*(\d{2})\s*-?\s*(\d{7})")


def parse_udyam(text):
    t = (text or "").upper().replace("O", "0") if False else (text or "").upper()
    out = {}
    m = UDYAM_RE.search(t)
    if m:
        out["udyam"] = f"UDYAM-{m.group(1)}-{m.group(2)}-{m.group(3)}"
    nm = _after(
        r"name\s*of\s*(?:the\s*)?enterprise\s*[:\-]?",
        text or "",
        stop_re=r"(?:type|organi[sz]ation|major|address|date|mobile|email)",
    )
    if nm:
        out["name"] = nm
    ty = re.search(
        r"type\s*of\s*enterprise[^A-Za-z]{0,20}(micro|small|medium)", text or "", re.I
    ) or re.search(r"\b(micro|small|medium)\s+enterprise", text or "", re.I)
    if ty:
        out["enterprise_class"] = ty.group(1).title()
    return out
