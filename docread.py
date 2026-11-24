"""Document reading for uploads. Returns what was read plus how confident we are; abstains rather than guesses.
Capture problems (rotation, skew, odd formats, multi-page PDFs, photos on a desk, bad light) are normalised by docprep first.
GSTIN/IFSC are accepted only when they pass their own checksum / the RBI list."""

import os, re
from PIL import Image
import pytesseract
import imgquality as Q
import docprep
from ocrgst import candidates, rapid_text
from ocr_ifsc import extract_ifsc
from validators import validate_gstin, validate_pan

DOC_WORDS = {
    "gst_cert": r"GST|REGISTRATION|TAX|INVOICE|GOVERNMENT",
    "cheque": r"IFSC|A/C|ACCOUNT|BANK|PAY|RUPEES|CHEQUE",
    "pan_card": r"INCOME|PERMANENT|ACCOUNT|PAN",
    "udyam_cert": r"UDYAM|ENTERPRISE|MSME|MICRO|SMALL",
}


def _gst_from_image(im, steps, expect=None):
    """Escalating attempts, cheapest first. Returns {gstin: how} (possibly empty) and the OCR text of the best attempt.
    `expect` is the GSTIN the vendor declared. An invoice carries the supplier's AND the buyer's GSTIN, so finding one valid
    GSTIN is not enough: while the declared one has not been seen, keep escalating to the stronger readers."""
    found, text = {}, ""
    done = lambda: bool(found) and (not expect or expect in found)

    def tess(img, tag):
        nonlocal text
        for v in _tess_variants(img):
            t = pytesseract.image_to_string(v)
            cands = candidates(t)
            text = (
                t if (cands and not found) or (not found and len(t) > len(text)) else text
            )  # keep the text of the attempt that actually read the certificate
            for g, h in cands.items():
                found.setdefault(g, h + tag)
            if done() and any(x.startswith("exact") for x in found.values()):
                break

    tess(im, "")
    if done():
        return found, text
    norm, log = docprep.normalise(im)
    if log:
        steps.extend(log)
        tess(norm, "+prepared")
    if done():
        return found, text
    for tag, img in (("+rapid", norm), ("+rapid+light", docprep.fix_lighting(norm)), ("+rapid-raw", im)):
        t = rapid_text(img)
        text = text if len(text) > len(t) else t
        for g, h in candidates(t).items():
            found.setdefault(g, h + tag)
        if done():
            break
    return found, text


def _tess_variants(im):
    from PIL import ImageOps, ImageFilter

    g = ImageOps.autocontrast(im.convert("L"))
    yield g
    big = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    yield big
    yield big.filter(ImageFilter.SHARPEN)


def read_document(kind, path, tmp="/tmp", expect=None):
    out = dict(kind=kind, abstained=False, steps=[])
    try:
        pages = docprep.load_pages(path)
    except docprep.DocError as e:
        out.update(abstained=True, how="unusable_file", error_code=e.code, error=e.vendor_msg)
        return out
    except Exception as e:
        out.update(
            abstained=True,
            how="unusable_file",
            error_code="error",
            error="This file could not be processed. Please upload a clear PDF or photo.",
        )
        return out
    out["pages"] = len(pages)
    qual = None
    all_text = []
    gst = {}
    ifsc = (None, "none")
    pans = set()
    name = None
    for i, (im, txt) in enumerate(pages):
        if im is not None and qual is None:
            qual = Q.verdict(Q.quality_metrics(im))
        if kind == "gst_cert":
            if im is None:  # digital PDF: exact windows over the text layer, label-anchored repair
                for g, h in candidates(txt).items():
                    gst.setdefault(g, h + "+text")
                all_text.append(txt)
            else:
                f, t = _gst_from_image(im, out["steps"], expect)
                all_text.append(t)
                for g, h in f.items():
                    gst.setdefault(g, h)
        elif kind == "cheque":
            if im is None:
                all_text.append(txt)
            else:
                t = pytesseract.image_to_string(im).upper()
                all_text.append(t)
                r = extract_ifsc(im)
                if not r[0]:  # retry on the normalised page
                    norm, log = docprep.normalise(im)
                    if log:
                        out["steps"].extend(log)
                        r = extract_ifsc(norm)
                    if not r[0]:
                        r = extract_ifsc(docprep.fix_lighting(norm))
                if r[0] and (
                    not ifsc[0] or (r[1].split("+")[0] in ("exact", "repaired") and ifsc[1] == "format-only")
                ):
                    ifsc = r
        elif kind == "udyam_cert":
            t = txt or (pytesseract.image_to_string(im) if im is not None else "")
            if im is not None and "UDYAM" not in t.upper():
                t = t + "\n" + rapid_text(im)
            all_text.append(t)
        elif kind == "pan_card":
            t = txt or (pytesseract.image_to_string(im).upper() if im is not None else "")
            if im is not None and not re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", t):
                t = rapid_text(im).upper()
            all_text.append(t)
            for x in re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", t):
                if validate_pan(x)[0]:
                    pans.add(x)
    out["text"] = "\n".join(all_text).upper()
    if qual:
        out["quality"] = qual
    if kind == "gst_cert":
        import certparse as CP

        pr = CP.parse_reg06("\n".join(all_text))
        if pr.get("legal_name"):
            out["name"] = pr["legal_name"].upper()
        else:
            m = re.search(r"LEGAL\s+NAME\s*[:\-]?\s*([^\n]{3,80})", out["text"])
            if m:
                out["name"] = m.group(1).strip()
        if pr.get("trade_name"):
            out["trade_name"] = pr["trade_name"].upper()
        out["composition"] = bool(pr.get("composition"))
        out["registration_type"] = pr.get("registration_type")
        out["doctype"] = (
            "certificate"
            if pr.get("is_reg06") or re.search(r"REGISTRATION\s+CERTIFICATE|REG-06", out["text"])
            else "invoice-like"
        )
        vals = list(gst)
        out["candidates"] = vals
        if len(vals) == 1:
            out.update(gstin=vals[0], how=gst[vals[0]])
        elif vals:
            out["how"] = "multiple"
        else:
            out["abstained"] = True
            out["how"] = "none"
    elif kind == "cheque":
        if ifsc[0]:
            out.update(ifsc=ifsc[0], how=ifsc[1])
        try:
            import cheque_verify as CV

            ims = [im for im, _ in pages if im is not None]
            if ims:
                out["micr"] = CV.micr_candidates(ims[0])
                out["account_candidates"] = CV.account_candidates(out["text"])
        except Exception as e:
            out["micr"] = []
        # a cheque is usable if ANY signal on it is readable: IFSC, MICR, bank name, account number (the typed IFSC is checked against the RBI list anyway)
        if not ifsc[0]:
            if out.get("micr") or out.get("account_candidates") or re.search(r"BANK|IFSC|MICR", out["text"]):
                out["how"] = "no_ifsc"
            else:
                out["abstained"] = True
                out["how"] = "none"
    elif kind == "udyam_cert":
        import certparse as CP

        up = CP.parse_udyam("\n".join(all_text))
        if up.get("udyam"):
            out.update(
                udyam=up["udyam"],
                how="exact",
                name=(up.get("name") or "").upper() or None,
                enterprise_class=up.get("enterprise_class"),
            )
        else:
            out["abstained"] = True
            out["how"] = "none"
    elif kind == "pan_card":
        import certparse as CP

        nm = CP.parse_pan_card("\n".join(all_text))
        if nm:
            out["name"] = nm.upper()
        if len(pans) == 1:
            out.update(pan=next(iter(pans)), how="exact")
        else:
            out["abstained"] = True
            out["how"] = "ambiguous" if pans else "none"
    if out["abstained"] and len(out["text"].strip()) > 60 and not re.search(DOC_WORDS[kind], out["text"]):
        out["wrong_type"] = True
    return out
