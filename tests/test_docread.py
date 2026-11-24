"""Regression tests for document reading on the generated demo documents (run make_demo.py first)."""

import json, docread

sc = json.load(open("data/demo/scenarios.json"))


def check(l, got, want):
    assert got == want, f"{l}: got {got!r} want {want!r}"
    print("ok", l)


h = sc["happy"]
d = docread.read_document("gst_cert", h["files"]["gst_cert"])
check("clean cert GSTIN", d.get("gstin"), h["form"]["gstin"])
check("cert is certificate", d.get("doctype"), "certificate")
check(
    "cert legal name read",
    (d.get("name") or "").lower().startswith(h["form"]["legal_name"].lower()[:12]),
    True,
)
c = docread.read_document("cheque", h["files"]["cheque"])
check("clean cheque IFSC", c.get("ifsc"), h["form"]["ifsc"])
p = docread.read_document("gst_cert", sc["photo"]["files"]["gst_cert"])
check("phone photo GSTIN", p.get("gstin"), sc["photo"]["form"]["gstin"])
b = docread.read_document("gst_cert", sc["blur"]["files"]["gst_cert"])
check("unreadable photo abstains", b.get("abstained"), True)
w = docread.read_document("gst_cert", sc["happy"]["files"]["cheque"])
check("cheque uploaded as certificate is not read as one", w.get("gstin"), None)
print("DOCREAD TESTS PASS")
