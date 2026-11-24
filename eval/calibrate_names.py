import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Calibrate name-match thresholds on REAL MCA names.
(1) Benign noise: real names rewritten in legitimate ways must still pass.
(2) Hard negatives: how close do DIFFERENT real companies get? -> false 'same vendor' / lookalike rate by threshold."""
import pandas as pd, random, json, re
from rapidfuzz import fuzz, process
from validators import normalise_name, name_score

R = random.Random(11)
df = pd.read_pickle("/tmp/mca.pkl")
act = df[
    (df.CompanyStatus == "Active") & df.is_cin & df.CompanyName.str.upper().str.endswith("PRIVATE LIMITED")
]
names = act.CompanyName.sample(6000, random_state=3).tolist()


def variants(n):
    base = re.sub(r"\s*PRIVATE LIMITED$", "", n.upper()).strip()
    return {
        "pvt_ltd": base + " PVT LTD",
        "pvt_dot": base + " PVT. LTD.",
        "private_ltd": base + " PRIVATE LTD",
        "p_ltd": base + " P LTD",
        "ms_prefix": "M/S " + n.upper(),
        "title_case": n.title(),
        "and_amp": n.upper().replace(" AND ", " & "),
        "dbl_space": n.upper().replace(" ", "  "),
        "no_suffix": base,
        "trailing_dot": n.upper() + ".",
    }


res = {}
for v in variants(names[0]):
    res[v] = [0, 0]
for n in names:
    for k, v in variants(n).items():
        s = name_score(n, v)
        res[k][0] += 1
        res[k][1] += s >= 85
benign = {k: f"{100*b/a:.1f}%" for k, (a, b) in res.items()}
# hard negatives: nearest DIFFERENT entity
pool = df[(df.CompanyStatus == "Active")].sample(300000, random_state=5)
pn = pool.CompanyName.map(normalise_name).tolist()
pc = pool.CIN.tolist()
byblock = {}
for i, n in enumerate(pn):
    byblock.setdefault(n[:3], []).append(i)
qs = R.sample(range(len(pn)), 8000)
sc = []
for qi in qs:
    cand = [j for j in byblock.get(pn[qi][:3], []) if j != qi and pc[j] != pc[qi]]
    if not cand:
        continue
    best = process.extractOne(pn[qi], [pn[j] for j in cand], scorer=fuzz.token_sort_ratio)
    sc.append(best[1])
n = len(sc)
thr = {t: f"{100*sum(1 for x in sc if x >= t)/n:.1f}%" for t in (95, 90, 85, 80, 70)}
out = {
    "benign_pass_rate_at_85": benign,
    "different_company_nearest_score_share_at_or_above": thr,
    "n_queries": n,
    "note": "share of real companies whose nearest DIFFERENT company scores >= threshold (sample pool 300k active)",
}
json.dump(out, open("data/real/name_calibration.json", "w"), indent=1)
print(json.dumps(out, indent=1))
