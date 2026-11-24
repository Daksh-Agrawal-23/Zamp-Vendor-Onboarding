"""Read one document with the same reader the app uses, and print what it found.

    python tools/read_document.py gst_cert samples/invoices/<file>.png
    python tools/read_document.py gst_cert samples/invoices/<file>.png --expect 33IZWCN4373L2Z3
    python tools/read_document.py cheque data/demo/happy_cheque.png

kinds: gst_cert, cheque, pan_card, udyam_cert
--expect  the GSTIN the vendor declared. Invoices carry the supplier's and the buyer's GSTIN, so with --expect the
          reader keeps trying stronger OCR until it has seen that one (this is what the web app does).
"""
import argparse, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import docread

ap = argparse.ArgumentParser()
ap.add_argument("kind", choices=["gst_cert", "cheque", "pan_card", "udyam_cert"])
ap.add_argument("path")
ap.add_argument("--expect", default=None, help="declared GSTIN (gst_cert only)")
a = ap.parse_args()
t = time.time()
d = docread.read_document(a.kind, a.path, expect=(a.expect or "").upper() or None)
print(f"file        : {a.path}")
print(f"time        : {time.time() - t:.1f}s")
print(f"abstained   : {d.get('abstained')}  ({d.get('error') or 'read ok'})")
q = d.get("quality") or {}
if q:
    print(f"image check : {q.get('level')}  {q.get('reasons') or q.get('tips') or ''}")
if a.kind == "gst_cert":
    print(f"GSTINs found: {sorted(d.get('candidates') or ([d['gstin']] if d.get('gstin') else []))}  (how: {d.get('how')})")
    if a.expect:
        found = a.expect.upper() in (d.get("candidates") or [d.get("gstin")])
        print(f"declared {a.expect.upper()} seen in document: {found}")
elif a.kind == "cheque":
    print(f"IFSC read   : {d.get('ifsc')}  (how: {d.get('how')})   MICR: {d.get('micr')}")
if d.get("steps"):
    print("steps       :", "; ".join(map(str, d["steps"])))
print("text sample :", " ".join((d.get("text") or "").split())[:160])
