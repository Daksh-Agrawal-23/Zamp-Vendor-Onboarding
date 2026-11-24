import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Capture-robustness harness: take clean fictional GST certificates and cheques and damage them the ways real vendors do.
Reports GSTIN/IFSC recovery per perturbation, and WRONG accepts (must be 0). Run: PYTHONPATH=. python3 eval_robustness.py [N] [--quick]"""
import json, os, sys, io, random, collections, tempfile, concurrent.futures as cf
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageOps
import make_demo, docread

random.seed(5)
np.random.seed(5)
W = tempfile.mkdtemp(prefix="rob_")
HI = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"


def pil(p):
    return Image.open(p).convert("RGB")


def cv(im):
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def back(a):
    return Image.fromarray(cv2.cvtColor(a, cv2.COLOR_BGR2RGB))


def rot_keep(im, a, bg=(120, 125, 130)):
    arr = cv(im)
    h, w = arr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * s + w * c), int(h * c + w * s)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    return back(cv2.warpAffine(arr, M, (nw, nh), borderValue=bg))


def on_desk(im, a=4, persp=0.0):
    arr = cv(im.resize((im.width // 2, im.height // 2)))
    h, w = arr.shape[:2]
    pad = 140
    bg = np.full((h + 2 * pad, w + 2 * pad, 3), (60, 85, 110), np.uint8)
    for _ in range(25):
        cv2.line(
            bg,
            (random.randint(0, bg.shape[1]), 0),
            (random.randint(0, bg.shape[1]), bg.shape[0]),
            (random.randint(40, 90),) * 3,
            random.randint(2, 9),
        )
    bg[pad : pad + h, pad : pad + w] = arr
    if persp:
        H, Wd = bg.shape[:2]
        src = np.float32([[0, 0], [Wd, 0], [Wd, H], [0, H]])
        d = persp * Wd
        dst = np.float32([[d, d * 0.5], [Wd - d * 0.3, 0], [Wd, H], [0, H - d]])
        bg = cv2.warpPerspective(
            bg, cv2.getPerspectiveTransform(src, dst), (Wd, H), borderValue=(60, 85, 110)
        )
    return rot_keep(back(bg), a, (60, 85, 110))


def gamma(im, g):
    return back((np.power(cv(im) / 255.0, g) * 255).astype(np.uint8))


def shadow(im, k=0.75):
    a = cv(im).astype(np.float32)
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    m = 1 - k * np.clip((xx / w + yy / h) - 0.7, 0, 1) * 1.6
    return back(np.clip(a * m[..., None], 0, 255).astype(np.uint8))


def glare(im):
    a = cv(im).astype(np.float32)
    h, w = a.shape[:2]
    m = np.zeros((h, w), np.float32)
    cv2.circle(m, (int(w * 0.6), int(h * 0.35)), int(h * 0.22), 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), h * 0.06)
    return back(np.clip(a + m[..., None] * 230, 0, 255).astype(np.uint8))


def blur(im, s):
    return back(cv2.GaussianBlur(cv(im), (0, 0), s))


def noise(im, s):
    a = cv(im).astype(np.float32)
    return back(np.clip(a + np.random.normal(0, s, a.shape), 0, 255).astype(np.uint8))


def lowres(im, f):
    return im.resize((int(im.width * f), int(im.height * f)), Image.BILINEAR)


def hindi(im):
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(HI, 30)
    d.text((90, 240), "भारत सरकार / वस्तु एवं सेवा कर पंजीकरण प्रमाणपत्र", font=f, fill="#222")
    d.text((90, 1520), "यह कंप्यूटर जनित प्रमाणपत्र है", font=f, fill="#222")
    return im


def jpg(im, q, path):
    im.save(path, quality=q)
    return path


def make_cases(base_png, tag):
    im = pil(base_png)
    out = {}

    def save(name, img, fmt="PNG", **kw):
        p = os.path.join(W, f"{tag}_{name}.{fmt.lower()}")
        img.save(p, fmt, **kw)
        out[name] = p

    save("clean", im)
    for a in (90, 180, 270):
        save(f"rot{a}", im.rotate(a, expand=True))
    for a in (-25, -12, -6, 6, 12, 25):
        save(f"skew{a:+d}", rot_keep(im, a, (255, 255, 255)))
    save(
        "exif_rot90",
        im.rotate(-90, expand=True).transpose(Image.FLIP_LEFT_RIGHT) if False else im.rotate(90, expand=True),
        "JPEG",
        quality=90,
    )
    p = out["exif_rot90"]
    ex = Image.open(p).getexif()
    ex[0x0112] = 6
    Image.open(p).save(p, exif=ex)  # pixels rotated, tag says rotate back
    save("desk", on_desk(im), "JPEG", quality=70)
    save("desk_perspective", on_desk(im, 6, 0.06), "JPEG", quality=65)
    save("dark", gamma(im, 3.2), "JPEG", quality=80)
    save("very_dark", gamma(im, 5.5), "JPEG", quality=80)
    save("washed_out", gamma(im, 0.3), "JPEG", quality=80)
    save("shadow", shadow(im), "JPEG", quality=80)
    save("glare", glare(im), "JPEG", quality=80)
    save("blur2", blur(im, 2.0), "JPEG", quality=80)
    save("blur4", blur(im, 4.0), "JPEG", quality=80)
    save("noise", noise(im, 25), "JPEG", quality=70)
    save("jpeg_q15", im, "JPEG", quality=15)
    save("lowres_0.5", lowres(im, 0.5), "JPEG", quality=70)
    save("lowres_0.3", lowres(im, 0.3), "JPEG", quality=70)
    save("hindi_overlay", hindi(im.copy()))
    save("webp", im, "WEBP", quality=80)
    save("tiff", im, "TIFF")
    save("bmp", im, "BMP")
    save("rgba_transparent", im.convert("RGBA"), "PNG")
    save("pdf_scan", im, "PDF", resolution=150)
    pg = Image.new("RGB", im.size, "white")
    ImageDraw.Draw(pg).text((300, 700), "Cover page - Terms of service", fill="black")
    p = os.path.join(W, f"{tag}_pdf_page2.pdf")
    pg.save(p, "PDF", save_all=True, append_images=[im], resolution=150)
    out["pdf_page2"] = p
    save("rot90_photo_dark", gamma(im.rotate(90, expand=True), 2.5), "JPEG", quality=70)
    save("desk_rot_blur", blur(on_desk(im, 15), 1.5), "JPEG", quality=60)
    with open(os.path.join(W, f"{tag}_corrupt.jpg"), "wb") as f:
        f.write(open(out["clean"], "rb").read()[:3000])
        out["corrupt_truncated"] = f.name
    with open(os.path.join(W, f"{tag}_empty.png"), "wb") as f:
        out["empty_file"] = f.name
    with open(os.path.join(W, f"{tag}_fake.jpg"), "wb") as f:
        f.write(b"MZ\x90\x00this is an exe")
        out["not_an_image"] = f.name
    return out


def one(args):
    kind, truth, name, path = args
    d = docread.read_document(kind, path, tmp=W)
    got = d.get("gstin") if kind == "gst_cert" else d.get("ifsc")
    cands = set(d.get("candidates") or ([got] if got else []))
    return dict(
        kind=kind,
        case=name,
        ok=truth in cands,
        wrong=bool(cands - {truth}) and truth not in cands or (len(cands - {truth}) > 0 and kind == "cheque"),
        abstained=d.get("abstained"),
        steps=d.get("steps"),
        err=d.get("error_code"),
    )


if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 6
    reg = {x["id"]: x for x in json.load(open("data/synth/registry.json"))}
    ids = [i for i in reg if reg[i]["gst_status"] == "Active"][:N]
    jobs = []
    for i in ids:
        v = reg[i]
        g, c = os.path.join(W, f"{i}_g.png"), os.path.join(W, f"{i}_c.png")
        make_demo.gst_cert(v, g)
        make_demo.cheque(v, c)
        for n, p in make_cases(g, i).items():
            jobs.append(("gst_cert", v["gstin"], n, p))
        if "--quick" not in sys.argv:
            for n in ("clean", "rot90", "rot180", "skew+12", "dark", "desk", "blur2", "pdf_scan", "webp"):
                cs = make_cases(c, i + "c")
                jobs.append(("cheque", v["ifsc"], n, cs[n]))
    print(len(jobs), "jobs", flush=True)
    with cf.ProcessPoolExecutor(2) as ex:
        rows = list(ex.map(one, jobs))
    agg = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        a = agg[(r["kind"], r["case"])]
        a[0] += 1
        a[1] += r["ok"]
        a[2] += bool(r["wrong"])
        a[3] += bool(r["abstained"])
    for (k, c), (n, ok, wr, ab) in sorted(agg.items()):
        print(f"{k:9s}{c:20s} read {ok}/{n}  wrong-accepted {wr}  abstained {ab}")
    json.dump(dict(rows=rows), open("data/real/eval_robustness.json", "w"))
    print("TOTAL wrong accepts:", sum(1 for r in rows if r["wrong"]))
