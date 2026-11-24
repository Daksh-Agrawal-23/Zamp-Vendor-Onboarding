import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Per-image: quality metrics + GSTIN recovery with BASELINE vs ENHANCED preprocessing. Parallel."""
import json, glob, re, sys, concurrent.futures as cf
from PIL import Image
import pytesseract
from validators import validate_gstin, suggest_gstin_fix
import imgquality as Q
from eval_docs import ocr_variants


def read(variants):
    from ocrgst import candidates

    got = {}
    for v in variants:
        for g, how in candidates(pytesseract.image_to_string(v)).items():
            got.setdefault(g, how)
        if any(h == "exact" for h in got.values()):
            break
    return set(got)


def one(r):
    p = glob.glob(f"data/real/hf/gst/images/syn_{r['id']}.*")[0]
    im = Image.open(p)
    truth = json.loads(r["label"])["supplier"]["gstin"]
    m = Q.quality_metrics(im)
    lab = json.loads(r["label"])
    allowed = {truth, (lab.get("buyer") or {}).get("gstin")} - {None}
    g1 = read(ocr_variants(im))
    base = truth in g1
    g2 = g1 if base else read(list(ocr_variants(im)) + Q.enhance_for_ocr(im))
    enh = truth in g2 or base
    from ocrgst import rapid_text, candidates as _c

    g3 = set(_c(rapid_text(im))) if not enh else set()
    full = enh or truth in g3
    return dict(
        id=r["id"],
        layout=r["layout"],
        level=r["level"],
        base=base,
        enh=enh,
        full=full,
        wrong=len((g1 | g2 | g3) - allowed),
        **m,
    )


if __name__ == "__main__":
    man = json.load(open("data/real/hf/gst/eval_manifest.json"))["synthetic"]
    with cf.ProcessPoolExecutor(2) as ex:
        rows = list(ex.map(one, man))
    json.dump(rows, open("data/real/eval_quality_rows.json", "w"))
    import collections

    agg = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        for k in (r["level"], "ALL"):
            agg[k][0] += 1
            agg[k][1] += r["base"]
            agg[k][2] += r["enh"]
    print(
        "wrong (non-supplier, non-buyer) GSTINs accepted:",
        sum(r["wrong"] for r in rows),
        "across",
        len(rows),
        "images",
    )
    for k, (n, b, e) in agg.items():
        print(
            f"{k:6s} n={n:3d} baseline={100*b/n:.0f}%  with enhanced preprocessing={100*e/n:.0f}%  full pipeline (+RapidOCR)={100*sum(r['full'] for r in rows if k=='ALL' or r['level']==k)/n:.0f}%"
        )
