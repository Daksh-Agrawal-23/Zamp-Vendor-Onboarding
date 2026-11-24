"""Document capture normalisation: everything a vendor can do wrong between 'photo taken' and 'OCR runs'.

Handles: file-format variety (JPEG/PNG/WebP/TIFF/BMP/GIF/HEIC if available/PDF), EXIF orientation, alpha channels, absurd sizes,
corrupt / empty / password-protected files, multi-page PDFs and TIFFs, 90/180/270 rotation, skew (+-30 deg), a document photographed on a
table (perspective crop), dark / washed-out / uneven lighting.
Every failure is a DocError with a reason a vendor can act on, never a crash or a silent guess."""

import io, os, re
import numpy as np, cv2
from PIL import Image, ImageOps, ImageFile
import pytesseract

ImageFile.LOAD_TRUNCATED_IMAGES = False
Image.MAX_IMAGE_PIXELS = 120_000_000
MAX_SIDE = 3500  # larger photos are downscaled: OCR gains nothing above this and time explodes
MIN_SIDE = 300  # below this nothing useful can be read
MAX_PAGES = 6


class DocError(Exception):
    def __init__(self, code, vendor_msg):
        super().__init__(vendor_msg)
        self.code, self.vendor_msg = code, vendor_msg


try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC = True
except Exception:
    HEIC = False


def sniff(path):
    with open(path, "rb") as f:
        h = f.read(16)
    if not h:
        raise DocError("empty", "The file is empty. Please upload it again.")
    if h.startswith(b"%PDF"):
        return "pdf"
    if h.startswith(b"\x89PNG"):
        return "png"
    if h[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[:2] == b"BM":
        return "bmp"
    if h[:3] == b"GIF":
        return "gif"
    if h[4:8] == b"ftyp" and h[8:12] in (b"heic", b"heix", b"mif1", b"hevc"):
        if HEIC:
            return "heic"
        raise DocError(
            "heic",
            "HEIC photos are not supported yet. Please share as JPG (iPhone: Settings > Camera > Formats > Most Compatible) or a PDF.",
        )
    raise DocError("format", "This file type is not supported. Please upload a PDF, JPG, PNG, WebP or TIFF.")


def _flatten(im):
    """EXIF rotation, alpha -> white, palette/CMYK/16-bit -> RGB."""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        bg = Image.new("RGB", im.size, "white")
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode in ("I;16", "I", "F"):
        im = Image.fromarray(
            (np.array(im, dtype=np.float32) / (np.array(im).max() or 1) * 255).astype(np.uint8)
        )
    return im.convert("RGB")


def _limit(im):
    w, h = im.size
    if min(w, h) < MIN_SIDE:
        raise DocError("tiny", f"The image is very small ({w}x{h}). Please upload a larger photo or scan.")
    if max(w, h) > MAX_SIDE:
        s = MAX_SIDE / max(w, h)
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return im


def load_pages(path):
    """-> list of (PIL RGB image or None, text-layer string or '') per page. Raises DocError."""
    kind = sniff(path)
    pages = []
    if kind == "pdf":
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as e:
            msg = str(e).lower()
            if "password" in msg:
                raise DocError("encrypted", "The PDF is password-protected. Please upload an unlocked copy.")
            raise DocError(
                "corrupt", "The PDF could not be opened (damaged file?). Please re-save and upload it again."
            )
        if len(pdf) == 0:
            raise DocError("empty", "The PDF has no pages.")
        for i in range(min(len(pdf), MAX_PAGES)):
            page = pdf[i]
            txt = ""
            try:
                txt = page.get_textpage().get_text_range() or ""
            except Exception:
                pass
            if len(txt.strip()) > 40:
                pages.append((None, txt))  # digital text layer: no OCR needed
            else:
                pages.append(
                    (_limit(_flatten(page.render(scale=2.5).to_pil())), "")
                )  # scanned page, about 180 dpi
        return pages
    try:
        im = Image.open(path)
        n = getattr(im, "n_frames", 1)
        for i in range(min(n, MAX_PAGES)):
            im.seek(i)
            pages.append((_limit(_flatten(im.copy())), ""))
    except DocError:
        raise
    except Exception:
        raise DocError(
            "corrupt", "The image could not be opened (damaged or incomplete upload). Please upload it again."
        )
    return pages


# ---------------------------------------------------------------- orientation ---------------------------------------------------
def _gray(im):
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)


def _word_score(im):
    """How much readable text does this orientation show? (count of confident dictionary-looking words)"""
    g = im.convert("L")
    s = 1100 / max(g.size)
    if s < 1:
        g = g.resize((int(g.width * s), int(g.height * s)))
    d = pytesseract.image_to_data(g, output_type=pytesseract.Output.DICT, config="--psm 6")
    return sum(
        1
        for t, c in zip(d["text"], d["conf"])
        if len(t.strip()) >= 4 and t.strip().isalpha() and float(c) > 60
    )


def fix_orientation(im):
    """Return (image, degrees_rotated). Tests the four rotations only when the upright one looks unreadable."""
    base = _word_score(im)
    if base >= 12:
        return im, 0
    best, ang = base, 0
    for a in (90, 180, 270):
        r = im.rotate(a, expand=True)
        sc = _word_score(r)
        if sc > best * 1.5 and sc >= 8:
            best, ang = sc, a
    return (im.rotate(ang, expand=True), ang) if ang else (im, 0)


# ---------------------------------------------------------------- skew ----------------------------------------------------------
def estimate_skew(im, span=30, step=1.0):
    """Projection-profile search: the angle at which text rows are sharpest. Range +-span degrees."""
    g = _gray(im)
    s = 700 / max(g.shape)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    h, w = bw.shape
    best, bang = -1, 0.0

    def score(a):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_NEAREST)
        return float(np.var(r.sum(axis=1)))

    for a in np.arange(-span, span + 1e-6, 2.0):  # coarse
        sc = score(a)
        if sc > best:
            best, bang = sc, a
    for a in np.arange(bang - 2, bang + 2.01, 0.5):  # fine
        sc = score(a)
        if sc > best:
            best, bang = sc, a
    return float(bang)


def deskew(im, threshold=1.0):
    a = estimate_skew(im)
    if abs(a) < threshold:
        return im, 0.0
    arr = np.array(im)
    h, w = arr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2 - w / 2
    M[1, 2] += nh / 2 - h / 2
    out = cv2.warpAffine(arr, M, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(out), a


# ---------------------------------------------------------------- document crop (photo on a desk) -----------------------------
def crop_document(im):
    """If a clearly lighter page sits on a darker/busier background, perspective-correct it. Otherwise return unchanged."""
    arr = np.array(im)
    h, w = arr.shape[:2]
    g = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    s = 800 / max(h, w)
    small = cv2.resize(g, None, fx=s, fy=s) if s < 1 else g
    blur = cv2.GaussianBlur(small, (7, 7), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return im, False
    c = max(cnts, key=cv2.contourArea)
    frac = cv2.contourArea(c) / (small.shape[0] * small.shape[1])
    if frac < 0.30 or frac > 0.93:
        return im, False  # nothing to crop, or page already fills the frame
    peri = cv2.arcLength(c, True)
    ap = cv2.approxPolyDP(c, 0.02 * peri, True)
    if len(ap) == 4:
        pts = ap.reshape(4, 2).astype(np.float32) / s
        sm, df = pts.sum(1), np.diff(pts, axis=1).ravel()
        tl, br, tr, bl = pts[sm.argmin()], pts[sm.argmax()], pts[df.argmin()], pts[df.argmax()]
        W = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        H = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        if W > 300 and H > 300:
            M = cv2.getPerspectiveTransform(
                np.array([tl, tr, br, bl], np.float32), np.array([[0, 0], [W, 0], [W, H], [0, H]], np.float32)
            )
            return Image.fromarray(cv2.warpPerspective(arr, M, (W, H), flags=cv2.INTER_CUBIC)), True
    x, y, bw_, bh_ = cv2.boundingRect(c)
    x, y, bw_, bh_ = [int(v / s) for v in (x, y, bw_, bh_)]
    return Image.fromarray(arr[y : y + bh_, x : x + bw_]), True


# ---------------------------------------------------------------- lighting ------------------------------------------------------
def fix_lighting(im):
    """Gamma for dark/bright captures, then flatten shadows by dividing out the illumination field."""
    g = _gray(im)
    m = g.mean()
    arr = np.array(im).astype(np.float32) / 255.0
    if m < 90:
        arr = arr ** (np.log(0.55) / np.log(max(m, 20) / 255.0))  # brighten
    elif m > 215:
        arr = arr**1.8  # un-wash
    arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
    g2 = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    bg = cv2.medianBlur(cv2.resize(g2, (max(g2.shape[1] // 8, 1), max(g2.shape[0] // 8, 1))), 21)
    bg = cv2.resize(bg, (g2.shape[1], g2.shape[0]))
    flat = cv2.divide(g2, np.maximum(bg, 1), scale=255)
    return Image.fromarray(cv2.cvtColor(flat, cv2.COLOR_GRAY2RGB))


def normalise(im):
    """Full capture normalisation; returns (clean image, log of what was done) so the audit trail can say what we did to the file."""
    log = []
    im, cropped = crop_document(im)
    if cropped:
        log.append("cropped page from background")
    im, ang = fix_orientation(im)
    if ang:
        log.append(f"rotated {ang} degrees")
    im, sk = deskew(im)
    if sk:
        log.append(f"deskewed {sk:+.1f} degrees")
    return im, log
