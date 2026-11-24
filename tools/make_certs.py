import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Fictional but layout-faithful renders of GST REG-06 (numbered table), PAN card and Udyam certificate, for reader tests. All data is invented."""
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
BOLD = "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"


def F(n, b=False):
    return ImageFont.truetype(BOLD if b else FONT, n)


def reg06(path, gstin, legal, trade, constitution, address, reg_type="Regular"):
    im = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(im)
    d.text((620, 70), "Government of India", font=F(30, True), anchor="mm", fill="#111")
    d.text((620, 118), "Form GST REG-06", font=F(26, True), anchor="mm", fill="#111")
    d.text((620, 170), "[See Rule 10(1)]", font=F(20), anchor="mm", fill="#333")
    d.text((620, 220), "Registration Certificate", font=F(34, True), anchor="mm", fill="#111")
    d.text((90, 300), "Registration Number :", font=F(26, True), fill="#111")
    d.text((420, 300), gstin, font=F(28, True), fill="#111")
    rows = [
        ("1.", "Legal Name", legal),
        ("2.", "Trade Name, if any", trade),
        ("3.", "Constitution of Business", constitution),
        ("4.", "Address of Principal Place of Business", address),
        ("5.", "Date of Liability", "01/07/2017"),
        ("6.", "Period of Validity     From  01/07/2017   To  Not Applicable", ""),
        ("7.", "Type of Registration", reg_type),
        ("8.", "Particulars of Approving Authority", "Signature Not verified"),
    ]
    y = 380
    for n, k, v in rows:
        d.rectangle([80, y, 1160, y + 110], outline="#444", width=2)
        d.line([420, y, 420, y + 110], fill="#444", width=2)
        d.text((95, y + 38), f"{n} {k}", font=F(22), fill="#222")
        for i, line in enumerate(_wrap(v, 38)):
            d.text((435, y + 20 + 30 * i), line, font=F(25, True), fill="#000")
        y += 130
    d.text(
        (620, 1660),
        "This is a system generated digital certificate and does not require signature.",
        font=F(18),
        anchor="mm",
        fill="#444",
    )
    im.save(path)
    return im


def _wrap(s, n):
    out, cur = [], ""
    for w in str(s).split():
        if len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return out + ([cur] if cur else [])


def pan_card(path, pan, name, father, dob="01/01/1980"):
    im = Image.new("RGB", (1011, 638), "#cfe3f5")
    d = ImageDraw.Draw(im)
    d.text((60, 30), "INCOME TAX DEPARTMENT", font=F(34, True), fill="#223")
    d.text((660, 30), "GOVT. OF INDIA", font=F(34, True), fill="#223")
    d.text((60, 120), "Permanent Account Number Card", font=F(26), fill="#223")
    d.text((60, 165), pan, font=F(50, True), fill="#111")
    d.text((60, 260), "Name", font=F(24), fill="#223")
    d.text((60, 295), name, font=F(34, True), fill="#111")
    d.text((60, 370), "Father's Name", font=F(24), fill="#223")
    d.text((60, 405), father, font=F(34, True), fill="#111")
    d.text((60, 480), "Date of Birth", font=F(24), fill="#223")
    d.text((60, 515), dob, font=F(32, True), fill="#111")
    im.save(path)
    return im


def udyam(path, number, name, klass="Small"):
    im = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(im)
    d.text((620, 90), "UDYAM REGISTRATION CERTIFICATE", font=F(36, True), anchor="mm", fill="#111")
    d.text((90, 220), "UDYAM REGISTRATION NUMBER :", font=F(26, True), fill="#111")
    d.text((90, 265), number, font=F(32, True), fill="#111")
    d.text((90, 360), "NAME OF ENTERPRISE :", font=F(26, True), fill="#111")
    d.text((90, 405), name, font=F(30, True), fill="#111")
    d.text((90, 500), f"TYPE OF ENTERPRISE :  {klass}", font=F(26, True), fill="#111")
    d.text((90, 580), "MAJOR ACTIVITY : Manufacturing", font=F(24), fill="#222")
    im.save(path)
    return im
