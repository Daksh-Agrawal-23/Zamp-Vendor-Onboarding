import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Prompt-injection / adversarial-text test: 24 invoices carrying hostile instructions inside the document (public HF set).
Our decision path has no language model, so text in a document can only influence us via the values we extract. Check: (1) every accepted GSTIN
is checksum-valid and belongs to the invoice (supplier/buyer), (2) the decision for a vendor whose declared GSTIN is the true one is unchanged."""
import json, glob, collections
import docread, engine

rows = [json.loads(l) for l in open("data/real/hf/gst/injection_metadata.jsonl")]
reg = engine.Registries()
out = collections.Counter()
detail = []
for r in rows:
    p = glob.glob(f"data/real/hf/gst/images/inj_{r['id']}.*")[0]
    lab = json.loads(r["label"])
    sup = lab["supplier"]["gstin"]
    buy = (lab.get("buyer") or {}).get("gstin")
    d = docread.read_document("gst_cert", p, tmp="/tmp")
    got = set(d.get("candidates") or [])
    out["read_supplier"] += sup in got
    out["foreign_gstin_accepted"] += len(got - {sup, buy}) > 0
    sub = dict(
        legal_name=lab["supplier"]["name"],
        country="IN",
        gstin=sup,
        pan=sup[2:12],
        ifsc="",
        account="",
        docs={"gst_cert": d},
    )
    res = engine.run(sub, reg)
    base = engine.run(dict(sub, docs={}), reg)
    changed = {f["rule"] for f in res["findings"]} - {f["rule"] for f in base["findings"]}
    out["decision_changed_by_document_text"] += bool(changed - {"R25"})
    detail.append(
        dict(id=r["id"], attack=r["attack"], style=r["attack_style"], read=sup in got, extra=sorted(changed))
    )
out["n"] = len(rows)
out["attacks"] = dict(collections.Counter(r["attack"] for r in rows))
print(dict(out))
json.dump(dict(summary=dict(out), detail=detail), open("data/real/eval_injection.json", "w"), indent=1)
