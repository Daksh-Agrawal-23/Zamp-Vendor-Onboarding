import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import sys, os, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import make_certs as MC, docread, validators as V
from PIL import Image

T = tempfile.mkdtemp()
ok = True


def check(n, c):
    global ok
    print(("ok   " if c else "FAIL ") + n)
    ok &= bool(c)


g = "27AAACS1234A1Z5"
while not V.validate_gstin(g)[0]:
    g = g[:-1] + V.B36[(V.B36.index(g[-1]) + 1) % 36]
p = os.path.join(T, "reg06.png")
MC.reg06(
    p,
    g,
    "SHARMA LOGISTICS PRIVATE LIMITED",
    "SHARMA CARGO",
    "Private Limited Company",
    "Plot 14, MIDC Andheri East, Mumbai, Maharashtra 400093",
)
d = docread.read_document("gst_cert", p, T)
check("REG-06 gstin", d.get("gstin") == g)
check("REG-06 legal name", (d.get("name") or "") == "SHARMA LOGISTICS PRIVATE LIMITED")
check("REG-06 trade name", d.get("trade_name") == "SHARMA CARGO")
check("REG-06 recognised as certificate", d.get("doctype") == "certificate")
p2 = os.path.join(T, "comp.png")
MC.reg06(
    p2,
    g,
    "GUPTA STORES",
    "GUPTA STORES",
    "Proprietorship",
    "Shop 3, Ring Road, Delhi",
    reg_type="Composition",
)
d2 = docread.read_document("gst_cert", p2, T)
check("composition registration detected from certificate", d2.get("composition") is True)
pp = os.path.join(T, "pan.png")
MC.pan_card(pp, "ABCPE1234F", "RAMESH KUMAR SHARMA", "SURESH SHARMA")
d3 = docread.read_document("pan_card", pp, T)
check("PAN number", d3.get("pan") == "ABCPE1234F")
check("PAN name (not father's name)", d3.get("name") == "RAMESH KUMAR SHARMA")
pu = os.path.join(T, "udy.png")
MC.udyam(pu, "UDYAM-MH-12-0012345", "ACME FOODS PRIVATE LIMITED")
d4 = docread.read_document("udyam_cert", pu, T)
check("Udyam number", d4.get("udyam") == "UDYAM-MH-12-0012345")
check(
    "Udyam name+class",
    d4.get("name") == "ACME FOODS PRIVATE LIMITED" and d4.get("enterprise_class") == "Small",
)
# photographed on a desk, rotated
im = Image.open(p).rotate(90, expand=True)
im.save(os.path.join(T, "rot.png"))
d5 = docread.read_document("gst_cert", os.path.join(T, "rot.png"), T)
check(
    "rotated REG-06 still read", d5.get("gstin") == g and d5.get("name") == "SHARMA LOGISTICS PRIVATE LIMITED"
)
print("CERT TESTS", "PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
