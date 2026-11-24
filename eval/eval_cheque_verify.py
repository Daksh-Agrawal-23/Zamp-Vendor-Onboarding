import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Real-cheque evaluation of claimed-IFSC verification. Positives: claimed = true IFSC. Negatives: claimed = a different bank / a different branch of the same bank.
Sets: IDRBT-derived scans (HF arunchincheti/handwritten_and_cheques_dataset, apache-2.0, 300dpi) + 12 real phone/web cheque photos (labels in data/real/cheque_labels.json)."""
import io, re, sys, json, random, collections, concurrent.futures as cf
import pandas as pd
from PIL import Image
import cheque_verify as cv
from ocr_ifsc import extract_ifsc
import pytesseract

random.seed(3)


def fulltext(im):
    t = ""
    for s in (1, 2):
        p = im.convert("L")
        p = p.resize((p.width * s, p.height * s))
        for cfg in ("--psm 6", "--psm 11"):
            t += "\n" + pytesseract.image_to_string(p, config=cfg)
    try:
        from ocrgst import rapid_text

        t += "\n" + rapid_text(im.convert("RGB"))
    except Exception:
        pass
    return t


WRONG_BANK = {
    "UTIB": "HDFC0003637",
    "ICIC": "UTIB0000426",
    "CNRB": "UTIB0000426",
    "SYNB": "ICIC0006308",
    "HDFC": "ICIC0006308",
    "BARB": "UTIB0000426",
    "PUNB": "ICIC0006308",
    "SBIN": "ICIC0006308",
}
SAME_BANK_OTHER_BRANCH = {
    "UTIB0000426": "UTIB0004410",
    "ICIC0006308": "ICIC0003494",
    "UTIB0004410": "UTIB0000426",
    "ICIC0003494": "ICIC0006308",
}


def run_one(args):
    path_or_bytes, truth, tag = args
    im = Image.open(io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes).convert(
        "RGB"
    )
    if max(im.size) > 3000:
        im.thumbnail((3000, 3000))
    txt = fulltext(im)
    r, how = extract_ifsc(im)
    micr = cv.micr_candidates(im)
    out = dict(tag=tag, truth=truth, read=r, how=how, cases={})
    cases = {"true": truth}
    cases["wrong_bank"] = WRONG_BANK.get(truth[:4], "ICIC0006308")
    if truth in SAME_BANK_OTHER_BRANCH:
        cases["same_bank_other_branch"] = SAME_BANK_OTHER_BRANCH[truth]
    for k, claimed in cases.items():
        v = cv.verify(claimed, im, ocr_text=txt, ifsc_read=r, ifsc_how=how, micr=micr)
        out["cases"][k] = dict(claimed=claimed, verdict=v["verdict"], signals=v["signals"], notes=v["notes"])
    return out


if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    jobs = []
    d = pd.read_parquet("/tmp/hfx/handwritten_and_cheques_dataset_train-00000-of-00001.parquet")
    by = collections.defaultdict(list)
    for i, a in enumerate(d.answers):
        m = re.search(r"'ifsc': '([A-Z0-9]{11})'", str(a))
        if m:
            by[m.group(1)].append(i)
    for ifsc, idx in by.items():
        for i in random.sample(idx, min(len(idx), max(2, N // 4 if ifsc.startswith("UTIB") else 4))):
            jobs.append((d.iloc[i].image["bytes"], ifsc, f"idrbt_{i}"))
    try:
        lab = json.load(open("data/real/cheque_labels.json"))
        for f, ifsc in lab.items():
            jobs.append((f"data/real/docs_real/{f}", ifsc, f))
    except Exception:
        pass
    print(len(jobs), "cheques", flush=True)
    rows = [run_one(j) for j in jobs]
    json.dump(rows, open("data/real/eval_cheque_verify.json", "w"), indent=1)
    for kind in ("true", "wrong_bank", "same_bank_other_branch"):
        c = collections.Counter(r["cases"][kind]["verdict"] for r in rows if kind in r["cases"])
        print(kind, dict(c))
