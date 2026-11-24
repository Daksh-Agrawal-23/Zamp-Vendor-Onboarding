"""Builds fictional demo documents (GST registration certificate, cancelled cheque) for synthetic vendors, in a clean-scan version and
degraded 'phone photo' versions (rotation, shadow gradient, blur, noise, JPEG), plus scenarios.json for the demo buttons.
All names/numbers are fictional (synthetic registry); nothing here is a real person or company."""

import json, os, random, numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

random.seed(11)
np.random.seed(11)
OUT = "data/demo"
os.makedirs(OUT, exist_ok=True)
F = lambda s, b=False: ImageFont.truetype(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if b else ""), s
)
reg = {x["id"]: x for x in json.load(open("data/synth/registry.json"))}


def gst_cert(v, path):
    im = Image.new("RGB", (1240, 1650), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, 1200, 1610], outline="#222", width=3)
    d.text((620, 90), "Government of India", font=F(34, True), fill="#111", anchor="mm")
    d.text((620, 140), "FORM GST REG-06", font=F(30, True), fill="#111", anchor="mm")
    d.text((620, 190), "Registration Certificate", font=F(28), fill="#111", anchor="mm")
    rows = [
        ("Registration Number", v["gstin"]),
        ("Legal Name", v["legal_name"]),
        ("Trade Name", v.get("trade_name") or v["legal_name"]),
        ("Constitution of Business", v["entity_type"]),
        ("Address of Principal Place of Business", v["address"]),
        ("Type of Registration", "Regular"),
        ("Date of Liability", "01/07/2017"),
    ]
    y = 300
    for k, val in rows:
        d.text((90, y), f"{k}", font=F(24), fill="#333")
        d.text((560, y), str(val), font=F(26, True), fill="#000")
        y += 120
        d.line([90, y - 35, 1150, y - 35], fill="#bbb", width=1)
    d.text(
        (90, 1450),
        "This is a computer generated certificate (fictional demo document).",
        font=F(20),
        fill="#555",
    )
    im.save(path)


def cheque(v, path, holder=None):
    im = Image.new("RGB", (1400, 640), "#f3efe2")
    d = ImageDraw.Draw(im)
    d.rectangle([15, 15, 1385, 625], outline="#555", width=3)
    d.text((60, 50), v["bank"].upper(), font=F(38, True), fill="#1a3d7c")
    d.text((60, 110), f"IFSC: {v['ifsc']}", font=F(30, True), fill="#111")
    d.text((1050, 60), "DATE  __ / __ / ____", font=F(24), fill="#333")
    d.text((60, 220), "PAY ____________________________________________", font=F(26), fill="#333")
    d.text((60, 330), "RUPEES ________________________________________", font=F(26), fill="#333")
    d.text((60, 470), f"A/c No. {v['account']}", font=F(28), fill="#111")
    d.text((60, 520), (holder or v["legal_name"]).upper(), font=F(30, True), fill="#111")
    d.text((1000, 540), "Authorised signatory", font=F(22), fill="#555")
    im.save(path)


def photo(src, dst, rot=3.0, blur=0.0, shadow=0.35, noise=6, scale=0.55, q=60):
    img = cv2.imread(src)
    h, w = img.shape[:2]
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    bg = np.full((h + 160, w + 160, 3), (70, 80, 90), np.uint8)
    bg[80 : 80 + h, 80 : 80 + w] = img
    M = cv2.getRotationMatrix2D((bg.shape[1] / 2, bg.shape[0] / 2), rot, 1.0)
    bg = cv2.warpAffine(bg, M, (bg.shape[1], bg.shape[0]), borderValue=(60, 70, 80))
    grad = np.tile(np.linspace(1 - shadow, 1.05, bg.shape[1]), (bg.shape[0], 1))[..., None]
    bg = np.clip(bg * grad, 0, 255)
    if blur:
        bg = cv2.GaussianBlur(bg, (0, 0), blur)
    bg = np.clip(bg + np.random.normal(0, noise, bg.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(dst, bg, [cv2.IMWRITE_JPEG_QUALITY, q])


def build():
    sc = {}

    def vend(i):
        return reg[i]

    def form(v, **kw):
        d = dict(
            country="IN",
            legal_name=v["legal_name"],
            gstin=v["gstin"],
            pan=v["pan"],
            cin=v["cin"] or "",
            state=v["state"],
            ifsc=v["ifsc"],
            account=v["account"],
            address=v["address"],
            expected_annual_value=1200000,
        )
        d.update(kw)
        return d

    def mk(vid, tag):
        v = vend(vid)
        g, c = f"{OUT}/{tag}_gst.png", f"{OUT}/{tag}_cheque.png"
        gst_cert(v, g)
        cheque(v, c)
        return v, g, c

    v, g, c = mk("E0001", "happy")
    sc["happy"] = dict(title="1. Clean vendor (happy path)", form=form(v), files=dict(gst_cert=g, cheque=c))
    v2, g2, c2 = mk("E0002", "typo")
    bad = v2["gstin"].replace("0", "O", 1)  # a letter O typed for the digit zero
    sc["typo"] = dict(
        title="2. Typo in GSTIN (vendor-fixable)",
        form=form(v2, gstin=bad),
        files=dict(gst_cert=g2, cheque=c2),
    )
    v3, g3, c3 = mk("E0003", "photo")
    photo(g3, f"{OUT}/photo_gst.jpg", rot=2.5, shadow=0.3, blur=0.6, scale=0.8, q=70)
    sc["photo"] = dict(
        title="3. Phone photo of GST certificate",
        form=form(v3),
        files=dict(gst_cert=f"{OUT}/photo_gst.jpg", cheque=c3),
    )
    v4, g4, c4 = mk("E0006", "blur")
    photo(g4, f"{OUT}/blur_gst.jpg", rot=5, shadow=0.5, blur=6.0, scale=0.3, noise=14, q=35)
    sc["blur"] = dict(
        title="4. Unreadable photo (asks for re-upload)",
        form=form(v4),
        files=dict(gst_cert=f"{OUT}/blur_gst.jpg", cheque=c4),
    )
    v5, g5, c5 = mk("E0025", "cancelled")
    sc["cancelled"] = dict(
        title="5. GSTIN cancelled in registry (reject)", form=form(v5), files=dict(gst_cert=g5, cheque=c5)
    )
    v6 = vend("E0007")
    g6, c6 = f"{OUT}/third_gst.png", f"{OUT}/third_cheque.png"
    gst_cert(v6, g6)
    cheque(v6, c6, holder="Ramesh Kulkarni Trading Co")
    sc["third"] = dict(
        title="6. Cheque belongs to a different party (escalate)",
        form=form(v6),
        files=dict(gst_cert=g6, cheque=c6),
    )
    v7, g7, c7 = mk("E0008", "bankchg")
    sc["bankchange"] = dict(
        title="7. Bank-detail change (call-back check)",
        form=form(v7, bank_change=True),
        files=dict(gst_cert=g7, cheque=c7),
    )
    v8, g8, c8 = mk("E0010", "retired")
    sc["retired"] = dict(
        title="8. Bank merged: old IFSC (vendor-fixable)",
        form=form(v8, ifsc="SYNB0000001"),
        files=dict(gst_cert=g8, cheque=c8),
    )
    v9, g9, c9 = mk("E0011", "outage")
    sc["outage"] = dict(
        title="9. GST portal down (never a silent pass)",
        form=form(v9, down_gst=True),
        files=dict(gst_cert=g9, cheque=c9),
    )
    json.dump(sc, open(f"{OUT}/scenarios.json", "w"), indent=1)


if __name__ == "__main__":
    build()
    print("built", len(os.listdir(OUT)), "files")
