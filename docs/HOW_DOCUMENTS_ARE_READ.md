# How documents are read

A vendor uploads whatever they have: a PDF, a phone photo, a scan. The reader's job is to turn that file into **values it can stand behind** (a GSTIN, an IFSC code, a PAN) or to **say it cannot** and ask for a better upload. It never guesses. The values are then compared with what the vendor typed (the claims) and with the registries (the evidence).

Code: `docread.py` (entry point `read_document`), with `docprep.py`, `imgquality.py`, `ocrgst.py`, `ocr_ifsc.py`, `cheque_verify.py`, `certparse.py`.
Try it on any file: `python tools/read_document.py gst_cert <file> [--expect <GSTIN>]`.

## 1. Load the file (`docprep.load_pages`)
Handles JPEG, PNG, WebP, TIFF, BMP, GIF, PDF (several pages), phone-camera rotation (EXIF), transparent backgrounds, huge or empty or corrupt or password-protected files. A **digital PDF** with a text layer is read from the text directly, with no OCR. A file that cannot be used becomes a message the vendor can act on ("please upload a clear PDF or photo"), never a crash.

## 2. Measure the quality (`imgquality`)
Sharpness, size, brightness, contrast, glare, uneven lighting and skew are measured. They give an `ok / warn / poor` verdict with reasons written for the vendor ("There is glare on the document. Tilt it slightly").
The thresholds come from data, not guesses: on 90 invoice images, sharpness (AUC 0.77) and image size (AUC 0.78) predicted whether the GSTIN could be read; glare and skew did not (about 0.6). The gate is **advisory**, because rejecting on quality alone would have bounced about 4 in 10 documents that were in fact readable. The vendor is asked to re-upload only when reading actually fails, and is given the specific reason.

## 3. Read the text, cheapest method first
1. **Tesseract** on the page, then on variants (auto-contrast, 2x upscale, sharpened).
2. If that is not enough, **normalise the capture** (`docprep.normalise`): fix 90/180/270 rotation, straighten skew up to about 30 degrees, crop a document photographed on a table, fix dark or washed-out lighting and shadows. The audit trail records what was done to the file.
3. If still not enough, a **second engine, RapidOCR** (ONNX models bundled in the package), which is far better on phone photos.
Each step is tried only when the cheaper one did not give an answer, so clean documents are fast (under a second for most) and only hard photos pay for the heavier readers.

## 4. Accept a value only if it checks out
- **GSTIN** (`ocrgst.candidates`): tolerant of what OCR does (spaces inside, O/0, S/5, Z/2 swaps, one stray character), but **every accepted value must pass the GSTIN check character**, the position pattern, and sit right after a GSTIN label. A misread can only become a wrong-but-valid number by also satisfying a 1-in-36 checksum.
- **Invoices carry two GSTINs** (the supplier's and the buyer's). So the reader is told the GSTIN the vendor declared (`expect`) and keeps escalating to the stronger readers until it has seen that one. If it still has not, the mismatch is reported; it is never "fixed" by picking the other number.
- **IFSC** (`ocr_ifsc`): multi-pass OCR plus dictionary repair against the RBI list (the 5th character is always 0; O/0 and I/1 confusions are repaired), and only values that exist in the RBI list are accepted.
- **GST certificates, PAN cards, Udyam certificates** (`certparse`): layout-tolerant parsers (a value may follow its label on the same line or on the next), then validated like any other identifier.

Example from the demo cheque: the printed code is `KKBK0RTGSMI`; the OCR text says `KKBKORTGSMI` (letter O for zero). The repair step checks the candidate against the RBI list and returns `KKBK0RTGSMI` marked as "repaired". Run `python tools/read_document.py cheque data/demo/happy_cheque.png` to see it.

## 5. Cheques are verified against the claim, not just read (`cheque_verify`)
On real cheques the IFSC is tiny print (2 to 3 mm), often unreadable, while the MICR band, the bank name and the branch name are large. So instead of only extracting the IFSC, the reader checks the cheque against the IFSC the vendor **claimed**, using four independent signals: the printed IFSC, the 9-digit MICR code (city, bank, branch), the bank name, and the branch or city text. Verdicts: `confirmed` (at least one strong signal agrees and none contradict), `partial`, `contradicted` (a strong signal names a different bank or branch), `unreadable`. A claimed code is never accepted from weak evidence alone, and an unreadable cheque becomes a hold for a person, never an approval.

## 6. What happens next
The reader returns the values, how each was obtained (`exact`, `repaired`, `+rapid`...), the image-quality verdict and the log of preparation steps. The rules engine compares them with the typed claims (rules R03 to R10 for GSTIN, PAN, IFSC and names, R25 for an unreadable document) and the result appears in the **claims vs evidence** table on every run.

## Why not a language model?
Rules and OCR make every result explainable and repeatable, and a document cannot instruct the system. (A test with 24 invoices containing hidden hostile instructions changed 0 decisions.) A model could later help read the messiest documents, behind the same rules and the same checksums.
