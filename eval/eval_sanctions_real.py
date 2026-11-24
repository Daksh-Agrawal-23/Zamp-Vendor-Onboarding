import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""False-flag test: real company names (GLEIF IN/GB/US + real MCA UP/MH sample) vs the real OFAC SDN list.
A hit is a false flag unless it is genuinely the same entity; with ~0 true sanctioned vendors in the sample we treat hits as candidates to review by eye."""
import json, random, pandas as pd
from rapidfuzz import process, fuzz
import engine, validators as V

random.seed(3)
reg = engine.Registries()
names = reg._names = [x for x, _ in reg._sn]
real = []
for f in ("gleif_in_all", "gleif_gb_all", "gleif_us_all"):
    for r in json.load(open(f"data/real/raw/{f}.json")):
        real.append(r["attributes"]["entity"]["legalName"]["name"])
real = random.sample(real, min(6000, len(real)))
m = (
    pd.read_csv("data/real/mca/up_or_mh_A.csv", usecols=["CompanyName"], low_memory=False)["CompanyName"]
    .dropna()
    .sample(6000, random_state=1)
    .tolist()
)
out = {}
for label, pool in (("GLEIF (IN/GB/US)", real), ("MCA (UP/MH)", m)):
    ns = [V.normalise_name(x) for x in pool]
    ns = [x for x in ns if x]
    out[label] = dict(n=len(ns))
    for th in (85, 90, 95, 100):
        hits = []
        for raw, n in zip(pool, ns):
            r = process.extractOne(n, names, scorer=fuzz.ratio, score_cutoff=th)
            if r:
                hits.append((raw, names[r[2]], round(r[1])))
        out[label][f"th{th}"] = len(hits)
        if th == 95:
            out[label]["examples95"] = hits[:12]
    print(label, {k: v for k, v in out[label].items() if k != "examples95"})
    for h in out[label]["examples95"][:8]:
        print("   ", h)
json.dump(out, open("data/real/eval_sanctions_real.json", "w"), indent=1)
