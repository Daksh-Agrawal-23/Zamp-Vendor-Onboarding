import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""All-cheque evaluation (shardable, resumable). Segments: idrbt_scan (labelled), hf_synth (30 synthetic cheques, bank known, IFSC label absent), real_photo (12 web photos; 6 labelled).
usage: python3 eval_cheque_all.py SHARD NSHARDS  -> appends to data/real/eval_cheque_all_<SHARD>.jsonl"""
import sys, io, json, os, re, glob
import pandas as pd
from PIL import Image
import cheque_verify as cv
from ocr_ifsc import extract_ifsc
from eval_cheque_verify import fulltext, WRONG_BANK, SAME_BANK_OTHER_BRANCH
import validators as V

BANKIFSC = {
    "syndicate": "SYNB0003011",
    "axis": "UTIB0000426",
    "canara": "CNRB0002854",
    "icici": "ICIC0006308",
}


def jobs():
    J = []
    for f in ("train", "test"):
        d = pd.read_parquet(f"/tmp/hfx/handwritten_and_cheques_dataset_{f}-00000-of-00001.parquet")
        for i, a in enumerate(d.answers):
            m = re.search(r"'ifsc': '([A-Z0-9]{11})'", str(a))
            if m:
                J.append(("idrbt_scan", f"{f}_{i}", d.iloc[i].image["bytes"], m.group(1)))
    s = pd.read_parquet("data/real/hf/cheques/test.parquet")
    for i, r in s.iterrows():
        J.append(("hf_synth", r["filename"], r["image"]["bytes"], None, BANKIFSC.get(str(r["bank"]).lower())))
    lab = json.load(open("data/real/cheque_labels.json"))
    for p in sorted(glob.glob("data/real/docs_real/cheque_*.jpg")):
        n = os.path.basename(p)
        J.append(("real_photo", n, open(p, "rb").read(), lab.get(n)))
    return J


def one(j):
    seg, tag, b, truth = j[:4]
    bankref = j[4] if len(j) > 4 else None
    im = Image.open(io.BytesIO(b)).convert("RGB")
    if max(im.size) > 3000:
        im.thumbnail((3000, 3000))
    txt = fulltext(im)
    r, how = extract_ifsc(im)
    micr = cv.micr_candidates(im)
    out = dict(
        seg=seg,
        tag=tag,
        truth=truth,
        read=r,
        how=how,
        read_in_rbi_list=bool(r and V.ifsc_exists(r)),
        cases={},
    )
    ref = truth or bankref
    cases = {}
    if truth:
        cases["true"] = truth
    if ref:
        cases["wrong_bank"] = WRONG_BANK.get(ref[:4], "ICIC0006308")
        if ref in SAME_BANK_OTHER_BRANCH:
            cases["same_bank_other_branch"] = SAME_BANK_OTHER_BRANCH[ref]
    for k, c in cases.items():
        v = cv.verify(c, im, ocr_text=txt, ifsc_read=r, ifsc_how=how, micr=micr)
        out["cases"][k] = dict(claimed=c, verdict=v["verdict"], signals=v["signals"])
    if not cases:
        out["unlabelled_verdict_vs_read"] = None
    return out


if __name__ == "__main__":
    sh, n = int(sys.argv[1]), int(sys.argv[2])
    J = jobs()
    mine = [j for i, j in enumerate(J) if i % n == sh]
    path = f"data/real/eval_cheque_all_{sh}.jsonl"
    done = set()
    if os.path.exists(path):
        done = {json.loads(l)["tag"] for l in open(path)}
    print(len(J), "total;", len(mine), "in shard", flush=True)
    for j in mine:
        if j[1] in done:
            continue
        try:
            o = one(j)
        except Exception as e:
            o = dict(seg=j[0], tag=j[1], error=str(e))
        open(path, "a").write(json.dumps(o) + "\n")
