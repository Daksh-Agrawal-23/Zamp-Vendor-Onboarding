"""Image quality gate + photo preprocessing for uploaded vendor documents.
Quality metrics are measured, then thresholds are set from data (see eval_quality.py), not guessed."""

import cv2, numpy as np
from PIL import Image


def _gray(img):
    a = np.array(img.convert("RGB"))
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)


def quality_metrics(img: Image.Image) -> dict:
    g = _gray(img)
    h, w = g.shape
    scale = 1000.0 / max(h, w)  # compare sharpness at a fixed working size
    s = cv2.resize(g, (int(w * scale), int(h * scale))) if scale < 1 else g
    sharp = float(cv2.Laplacian(s, cv2.CV_64F).var())
    mean, std = float(g.mean()), float(g.std())
    glare = float((g >= 250).mean())
    # illumination unevenness: spread of block means (shadows / lighting gradient)
    bh, bw = max(h // 8, 1), max(w // 8, 1)
    blocks = [
        g[i : i + bh, j : j + bw].mean() for i in range(0, h - bh + 1, bh) for j in range(0, w - bw + 1, bw)
    ]
    uneven = float(np.std(blocks))
    return dict(
        width=w,
        height=h,
        min_side=min(h, w),
        sharpness=round(sharp, 1),
        brightness=round(mean, 1),
        contrast=round(std, 1),
        glare=round(glare, 4),
        unevenness=round(uneven, 1),
        skew=round(estimate_skew(g), 2),
    )


def estimate_skew(g) -> float:
    """Dominant text-line angle in degrees (small-angle), via minAreaRect of dark pixels."""
    small = cv2.resize(g, (g.shape[1] // 2 or 1, g.shape[0] // 2 or 1)) if max(g.shape) > 1600 else g
    bw = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    ys, xs = np.where(bw > 0)
    if len(xs) < 500:
        return 0.0
    pts = np.column_stack([xs, ys]).astype(np.float32)
    ang = cv2.minAreaRect(pts)[-1]
    ang = ang - 90 if ang > 45 else ang
    return float(ang if abs(ang) <= 15 else 0.0)


def verdict(m: dict, th=None) -> dict:
    """ok / warn / poor, with reasons phrased for the vendor."""
    th = th or THRESHOLDS
    reasons = []
    wide = (
        max(m["width"], m["height"]) / max(m["min_side"], 1) >= 1.6
    )  # cheques: judge long side, short side is naturally small
    small = (max(m["width"], m["height"]) < 1000) if wide else (m["min_side"] < th["min_side"])
    if small:
        reasons.append(
            "The image is too small. Please upload a larger photo or scan (at least 1000 pixels on the short side)."
        )
    if m["sharpness"] < th["sharpness"]:
        reasons.append(
            "The image looks blurry. Hold the phone steady and tap to focus before taking the photo."
        )
    if m["brightness"] < th["dark"]:
        reasons.append("The image is too dark. Take it in good light.")
    if m["glare"] > th["glare"]:
        reasons.append("There is glare on the document. Tilt it slightly or move away from direct light.")
    if m["unevenness"] > th["unevenness"]:
        reasons.append("Lighting is uneven or a shadow falls across the page.")
    if abs(m["skew"]) > th["skew"]:
        reasons.append("The page is tilted. Place it flat and photograph it straight on.")
    level = "poor" if (m["sharpness"] < th["sharpness"] or small) else ("warn" if reasons else "ok")
    return dict(level=level, reasons=reasons)


# Calibrated on 90 real invoice images (eval_quality_rows.json): sharpness<1000 or short side<700 flags 29 images,
# of which only 41% still read vs 84% of unflagged. A flag is a risk signal, NOT proof of failure (41% still read),
# so the engine treats it as advisory and asks for a re-upload only when extraction itself abstains.
THRESHOLDS = dict(min_side=700, sharpness=1000.0, dark=70, glare=0.12, unevenness=38.0, skew=6.0)


def enhance_for_ocr(img: Image.Image) -> list:
    """Photo-oriented variants: flatten lighting, deskew, upscale, local contrast. Returns PIL images to OCR."""
    g = _gray(img)
    h, w = g.shape
    ang = estimate_skew(g)
    if abs(ang) > 0.7:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        g = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    bg = cv2.medianBlur(cv2.resize(g, (w // 8 or 1, h // 8 or 1)), 21)
    bg = cv2.resize(bg, (w, h))
    flat = cv2.divide(g, np.maximum(bg, 1), scale=255)  # divide out the illumination field
    target = 2200 / max(w, 1)
    up = cv2.resize(flat, None, fx=target, fy=target, interpolation=cv2.INTER_CUBIC) if target > 1 else flat
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(up)
    thr = cv2.adaptiveThreshold(up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 12)
    return [Image.fromarray(clahe), Image.fromarray(thr)]
