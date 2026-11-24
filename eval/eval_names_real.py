import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Name matcher on REAL company names (MCA UP+MH). Positives: realistic re-writings of the same name (should not conflict, ideally pass).
Negatives: a DIFFERENT real company chosen as the nearest neighbour by string similarity (should not pass). Writes data/real/eval_names_real.json."""
import random, re, json, collections
import pandas as pd
from rapidfuzz import process, fuzz
import validators as V

random.seed(11)
df = pd.read_csv("data/real/mca/up_or_mh_A.csv", usecols=["CompanyName", "CompanyStatus"]).dropna()
df = df[df.CompanyStatus == "Active"].CompanyName.str.strip().str.upper().drop_duplicates()
names = [n for n in df.tolist() if 8 <= len(n) <= 60 and re.search(r"(PRIVATE LIMITED|LIMITED)$", n)]
sample = random.sample(names, 3000)
ABBR = [
    ("ENGINEERING", "ENGG"),
    ("INDUSTRIES", "INDS"),
    ("ENTERPRISES", "ENT"),
    ("TECHNOLOGIES", "TECH"),
    ("LABORATORIES", "LABS"),
    ("CONSTRUCTIONS", "CONST"),
    ("INTERNATIONAL", "INTL"),
    ("SERVICES", "SVCS"),
    ("SOLUTIONS", "SOLN"),
    ("MANUFACTURING", "MFG"),
    ("CORPORATION", "CORPN"),
]


def variants(n):
    base = re.sub(r" (PRIVATE LIMITED|LIMITED)$", "", n)
    suf = "PRIVATE LIMITED" if n.endswith("PRIVATE LIMITED") else "LIMITED"
    v = {
        "suffix_pvt_ltd": base + (" PVT LTD" if suf == "PRIVATE LIMITED" else " LTD"),
        "suffix_p_ltd": base + (" (P) LTD" if suf == "PRIVATE LIMITED" else " LTD."),
        "ms_prefix_lower": "M/s " + n.title(),
        "no_suffix": base,
        "ampersand": n.replace(" AND ", " & ") if " AND " in n else None,
        "the_dropped": n[4:] if n.startswith("THE ") else None,
        "punct_spaces": "  ".join(n.split()).replace(" ", "  ", 1),
    }
    for a, b in ABBR:
        if a in n:
            v["abbr_" + a.lower()] = n.replace(a, b)
            break
    toks = base.split()
    if len(toks) >= 2:
        v["order_swap"] = " ".join(toks[1:] + toks[:1]) + " " + suf
    return {k: x for k, x in v.items() if x}


pos = collections.defaultdict(lambda: collections.Counter())
fails = []
for n in sample:
    for k, x in variants(n).items():
        b = V.name_band(V.name_score(n, x))
        pos[k][b] += 1
        if b != "pass" and len(fails) < 60:
            fails.append((k, n, x, b))
# negatives: nearest DIFFERENT real company (same first word, highest similarity)
bucket = collections.defaultdict(list)
for n in names:
    bucket[n.split()[0]].append(n)
neg = collections.Counter()
neg_ex = []
for n in sample[:1500]:
    cand = [c for c in bucket[n.split()[0]] if c != n]
    if not cand:
        continue
    m = process.extractOne(n, cand, scorer=fuzz.token_sort_ratio)
    b = V.name_band(V.name_score(n, m[0]))
    neg[b] += 1
    if b == "pass" and len(neg_ex) < 40:
        neg_ex.append((n, m[0]))
out = dict(
    n_sample=len(sample),
    positives={k: dict(v) for k, v in pos.items()},
    negatives=dict(neg),
    failures=fails,
    false_pass_examples=neg_ex,
)
json.dump(out, open("data/real/eval_names_real.json", "w"), indent=1)
tot = collections.Counter()
for k, v in pos.items():
    tot.update(v)
print("positives", dict(tot))
[print(" ", k, dict(v)) for k, v in pos.items()]
print("negatives (nearest different real company)", dict(neg))
print("false-pass examples:")
[print("  ", a, "|", b) for a, b in neg_ex[:15]]
print("positive misses:")
[print("  ", f) for f in fails[:15]]
