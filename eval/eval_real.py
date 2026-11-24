import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Run the deterministic rules over REAL Indian entities (GLEIF public records).
Measures how often rules would wrongly flag a genuine entity (false-block / false-flag rate)."""
import json, re, collections
from validators import *

FORM_PAN = {
    "C": "Company",
    "F": "Firm/LLP",
    "P": "Individual",
    "H": "HUF",
    "A": "AOP",
    "T": "Trust",
    "G": "Govt",
    "B": "BOI",
    "L": "Local",
    "J": "AJP",
}

d = json.load(open("data/real/raw/gleif_in_all.json"))
c = collections.Counter()
ex = collections.defaultdict(list)
for r in d:
    e = r["attributes"]["entity"]
    name = e["legalName"]["name"]
    rid = (e.get("registeredAs") or "").strip().upper()
    reg = (e["legalAddress"].get("region") or "").replace("IN-", "")
    if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", rid) and validate_gstin(rid)[0]:
        c["gstin_valid"] += 1
        pan = pan_from_gstin(rid)
        c["pan_struct_ok"] += validate_pan(pan)[0]
        if not validate_pan(pan)[0]:
            ex["pan_struct"].append((rid, name))
        if reg:
            c["gst_state_checked"] += 1
            ok = gstin_state_matches(rid, reg)
            c["gst_state_match"] += ok
            if not ok:
                ex["gst_state"].append((rid, reg, name))
        h = pan_name_hint(pan, name)
        if h is not None:
            c["pan5_checked"] += 1
            c["pan5_match"] += h
            if not h:
                ex["pan5"].append((pan, name))
        # PAN 4th char vs suffix in the name
        n = normalise_suffix_text(name)
        if pan[3] == "C":
            c["c_checked"] += 1
            c["c_has_suffix"] += any(w in n for w in ("LIMITED", "PRIVATE", "COMPANY", "CORPORATION"))
        if pan[3] == "F":
            c["f_checked"] += 1
            c["f_has_suffix"] += any(
                w in n for w in ("LLP", "FIRM", "PARTNERSHIP", "TRADERS", "ENTERPRISES", "AND", "CO")
            )
        if pan[3] == "P":
            c["p_checked"] += 1
            c["p_company_suffix"] += any(w in n.split() for w in ("LIMITED", "PRIVATE", "LLP"))
    elif re.fullmatch(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", rid) and validate_cin(rid)[0]:
        p = parse_cin(rid)
        c["cin_valid"] += 1
        if reg:
            c["cin_state_checked"] += 1
            ok = cin_state_matches(rid, reg)
            c["cin_state_match"] += ok
            if not ok:
                ex["cin_state"].append((rid, reg, name))
        h = cin_name_consistent(rid, name)
        if h is not None:
            c["cin_name_checked"] += 1
            c["cin_name_match"] += h
            if not h:
                ex["cin_name"].append((rid, name))


def pct(a, b):
    return f"{a}/{b} = {100*c[a]/max(c[b],1):.1f}%"


print("REAL entities (GLEIF, India):", len(d))
print("GSTIN-derived PAN structure valid:", pct("pan_struct_ok", "gstin_valid"))
print("GSTIN state code vs registered-address state:", pct("gst_state_match", "gst_state_checked"))
print("CIN state code vs registered-address state:  ", pct("cin_state_match", "cin_state_checked"))
print("CIN class vs 'Private/Public Limited' name:  ", pct("cin_name_match", "cin_name_checked"))
print("PAN 5th char vs name initial (soft rule):    ", pct("pan5_match", "pan5_checked"))
print("PAN type 'C' names carrying a company suffix:", pct("c_has_suffix", "c_checked"))
print(
    "PAN type 'P' names carrying a company suffix:", pct("p_company_suffix", "p_checked"), "(lower is better)"
)
for k in ex:
    print(k, "mismatches e.g.:", ex[k][:3])
json.dump(
    {"counts": c, "examples": {k: v[:10] for k, v in ex.items()}},
    open("data/real/real_rule_eval.json", "w"),
    indent=1,
)
