import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Document-parsing evaluation with ground truth (public HF datasets, kept local).
1) GSTIN extraction on synthetic Indian GST invoices, by layout/scan level (Divya52/indian-gst-invoices, CC-BY-4.0).
2) IFSC extraction from the annotated IFSC box on Indian cheques (jaganadhg/cheque-synthetic-images, Apache-2.0)."""
import json, re, glob, io, collections, sys
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from validators import validate_gstin, suggest_gstin_fix, validate_ifsc, ifsc_exists
from ocr_ifsc import _candidates


def ocr_variants(im):
    g = ImageOps.autocontrast(im.convert("L"))
    yield g
    big = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    yield big
    yield big.filter(ImageFilter.SHARPEN)


def gstin_from_image(path):
    """Checksum-validated GSTINs from an image across several preprocessing variants (see ocrgst.candidates)."""
    from ocrgst import candidates

    im = Image.open(path)
    got = {}
    for v in ocr_variants(im):
        for g, how in candidates(pytesseract.image_to_string(v)).items():
            got.setdefault(g, how)
        if any(h == "exact" for h in got.values()):
            break
    return list(got.items())


def run_gst():
    man = json.load(open("data/real/hf/gst/eval_manifest.json"))
    res = collections.defaultdict(lambda: [0, 0, 0])
    for r in man["synthetic"]:
        p = glob.glob(f"data/real/hf/gst/images/syn_{r['id']}.*")[0]
        lab = json.loads(r["label"])
        truth = {lab["supplier"]["gstin"], (lab.get("buyer") or {}).get("gstin")} - {None}
        sup = lab["supplier"]["gstin"]
        found = gstin_from_image(p)
        got = {g for g, _ in found}
        key = f"{r['layout']}/{r['level']}"
        res[key][0] += 1
        res[key][1] += sup in got
        res[key][2] += len(got - truth) == 0
        res["ALL"][0] += 1
        res["ALL"][1] += sup in got
        res["ALL"][2] += len(got - truth) == 0
    return {
        k: dict(n=v[0], supplier_gstin_recovered=v[1], no_wrong_gstin=v[2]) for k, v in sorted(res.items())
    }


def run_cheques():
    import pandas as pd

    df = pd.read_parquet("data/real/hf/cheques/test.parquet")
    out = collections.Counter()
    banks = collections.defaultdict(lambda: collections.Counter())
    for _, r in df.iterrows():
        im = Image.open(io.BytesIO(r["image"]["bytes"]))
        b = r["ifsc"]
        pad = 12
        box = (max(b["xmin"] - pad, 0), max(b["ymin"] - pad, 0), b["xmax"] + pad, b["ymax"] + pad)
        crop = im.crop(box)
        txt = ""
        for s in (2, 3):
            c = ImageOps.autocontrast(crop.convert("L")).resize(
                (crop.width * s, crop.height * s), Image.LANCZOS
            )
            for cfg in ("--psm 7", "--psm 6"):
                txt += " " + pytesseract.image_to_string(c, config=cfg).upper()
        flat = re.sub(r"[^A-Z0-9]", "", txt)
        cands = set(re.findall(r"[A-Z]{4}0[A-Z0-9]{6}", flat))
        for m in re.finditer(r"[A-Z0-9]{11}", flat):
            cands |= _candidates(m.group(0))
        ok = [c for c in cands if validate_ifsc(c)[0] and ifsc_exists(c)]
        got = "exists" if len(set(ok)) == 1 else "ambiguous" if ok else "none"
        out[got] += 1
        banks[r["bank"]][got] += 1
    return {"n": len(df), **out, "by_bank": {k: dict(v) for k, v in banks.items()}}


if __name__ == "__main__":
    which = sys.argv[1]
    res = run_gst() if which == "gst" else run_cheques()
    json.dump(res, open(f"data/real/eval_docs_{which}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
