# Data sources and provenance

All data is public (full inventory with links: [data/README.md](../data/README.md)). Real documents and datasets are used only as local test inputs for parsing and rule evaluation; none are shown in the demo. Only the 12 invoice images in `samples/invoices` (CC-BY-4.0, attribution in `samples/invoices/ATTRIBUTION.md`) and the small result files are redistributed here; the real cheque images and the MCA records stay local. Demo vendors are fictional.

| Data | Source | Licence / status | Used for |
|---|---|---|---|
| Indian legal entities (6,000 IN, 1,600 US, 1,600 GB) | GLEIF public API, fetched 2026-11-23 | Open (CC0) | Validating GSTIN/CIN rules on real identifiers; state, name and form patterns |
| OFAC SDN list (19,599 records, with aliases) | US Treasury OFAC, published 2026-11-19 | US government public data | Sanctions screening |
| RBI bank codes and IFSC existence list (260 banks, 183,214 branch codes) | Razorpay IFSC dataset (derived from RBI lists) | Public domain | IFSC format, bank and existence checks |
| 12 cheque images | Public explainer pages | Local test only, never redistributed | Real-world OCR baseline (first-pass IFSC print reading was 4/12; later replaced by claim verification, see DECISIONS §18) |
| 30 Indian cheque images, IFSC box annotated | Hugging Face `jaganadhg/cheque-synthetic-images` | Apache-2.0 | IFSC extraction (19/30 recovered and verified) |
| 90 GST invoice images + 24 prompt-injection invoices, with ground truth | Hugging Face `Divya52/indian-gst-invoices` | CC-BY-4.0 | GSTIN extraction by layout and scan quality; injection robustness |
| MCA company and LLP master data, UP + Maharashtra (1,051,234 records: 854,324 CINs, 195,343 LLPINs) | data.gov.in via the user's download request, hosted on Hugging Face | Open government data; local only | Rule calibration, name thresholds, MCA status base rates |
| Blank GST REG-06 form, IRS W-9 | taxindiaonline.com, irs.gov | Public forms | Layout reference |

## Not obtainable, and what stands in
- MCA data for other states: only UP and Maharashtra were obtained.
- GST registry and PAN status services: no public bulk data; simulated.

## Findings recorded from real data
- 2,998 of 3,000 real GSTINs and 1,878 of 1,878 CINs pass; the two GSTIN failures are real data-entry errors (one is I typed for 1, which the repair step fixes).
- A state-code mismatch for Telangana (GST 36 appears as region TS) would have wrongly flagged real vendors.
- CIN state codes are registrar-office codes and some are historical, so that check is informational only.
- PAN 5th-character check: 75% of real entities matched at first; calibrated to 87% by skipping business names under personal PANs. Stays a low-weight hint.
- Merged banks (for example Syndicate into Canara) leave a bank code with no live branches. That is a vendor-fixable case, not fraud.
- FIRST-PASS BASELINE (Tesseract only, superseded by the final table below; file eval_docs_gst.json): GSTIN extraction on 90 invoices: 67% recovered overall (about 88% on clean and scanned, 38-46% on phone photos). In all 90, the checksum meant no wrong GSTIN was ever accepted. The system abstains instead of guessing.

## Findings from 1.05 million real MCA records
- 26.8% of records are not Active (240,474 Struck Off, plus liquidation, amalgamation, CIRP). An MCA status check is high-value.
- CIN validation initially rejected 0.5% of real CINs: a Nidhi company class (PLN) was missing. All 14 observed class codes are now accepted (99.99% valid).
- CIN year equals the incorporation year in 99.97% of records, so a mismatch is a strong typo or forgery signal.
- Class-versus-name: the direction "named Limited but class PTC" is common (37,525 real private companies, many Farmer Producer Companies) and was wrongly flagged. Only "Private Limited name with a public class" is kept, at a 0.18% false-flag rate.
- Name normalisation: "P LTD" (766 names), the "M/S" prefix and names made only of suffix words were mishandled; fixed. Benign rewrites of real names (Pvt Ltd, Private Ltd, P Ltd, M/S, ampersand, case, spacing) now pass 100%.
- Names are not identities: 10.2% of real companies have a different real company scoring 85+ on name, 3.1% score 90+, and 0.3% score 95+. So name score cannot decide "same vendor" alone; use 95+ with a different tax ID as the lookalike alert.
- Address concentration: 47 registered addresses hold 50 or more entities (the largest holds 8,799). Only 2.8% of entities sit at an address shared by 10+, so this is a usable soft signal.

## Image-quality gate calibration (90 real invoice images)
- Sharpness (AUC 0.77) and image size (AUC 0.78) predict whether the GSTIN can be read; glare and skew are weak (0.59/0.60).
- Gate at sharpness < 1000 or short side < 700: flags 29/90; 41% of flagged still read vs 84% of unflagged.
- Design decision: the gate is advisory. A hard rejection on quality alone would wrongly bounce ~4 in 10 readable documents, so the vendor is asked to re-upload only when extraction abstains, using the specific reason from the gate.

## Engine evaluation (eval/eval_engine.py, eval/eval_sanctions_real.py)
- Synthetic labelled sets (dev/held-out split by vendor id): 172 healthy vendors x 8 benign name variations -> 0/1,548 wrongly blocked; 15 injected defect types x ~170 vendors -> every defect fires the intended rule at the intended severity. Caveat: author wrote both sides, so this proves plumbing, not real-world accuracy. Mutation-labelling bugs found and fixed (no-op transpositions, accidentally similar "different" vendors) are listed in the decision log.
- Real names vs real OFAC SDN (6,000 GLEIF + 6,000 MCA names): flags at name-similarity 85/90/95/100 = 91/13/3/3 (GLEIF), 89/6/0/0 (MCA). Operating point 95. The 3 hits are single-word personal names (e.g. "AMBER", "RAMYA") that exactly match SDN individuals -> single short-word names are not escalated on name alone (logged only).

## Second OCR engine and injection test (eval/eval_quality.py, eval/eval_injection.py, eval/eval_cheques_real.py)
- 90 public synthetic GST invoice images (Divya52/indian-gst-invoices, CC-BY-4.0), clean/scan/photo: Tesseract 71% -> + preprocessing 74% -> + RapidOCR 98% (photos 42% -> 50% -> 95%). 0 wrong GSTINs accepted. Photo degradation in this dataset is simulated.
- 12 real public cheque photos: IFSC verified against the RBI list on 4/12 with either engine. Remaining failures: old/merged-bank codes (e.g. a Punjab National Bank cheque printing a legacy code absent from the RBI list), low resolution, rotated text.
- 24 prompt-injection invoices from the same dataset: supplier GSTIN read on 22/24, 0 foreign GSTINs accepted, 0 decisions changed.


## Single source of truth for reading accuracy (final pipeline)
GSTIN on 90 invoice images: 71% (Tesseract) -> 74% (+prep) -> 98% (+RapidOCR), per-row data in eval_quality_rows.json (`base`/`enh`/`full`); the 67% in eval_docs_gst.json is the earlier Tesseract-only baseline. Real cheques: 4/12 IFSC codes verified against the RBI list (weakest component; demo cheques are clean synthetic renders, so the demo does not exercise this). Registry checks (GST/PAN/Udyam/bank) are simulated over a generated registry; real-data results cover identifiers, names, sanctions and OCR only.

## Added in the market-readiness pass
- Real cheque scans with IFSC labels: Hugging Face `arunchincheti/handwritten_and_cheques_dataset` (apache-2.0), 102 labelled scans of 4 banks (Axis, ICICI, Canara, Syndicate); 22 used in the evaluation, local only.
- IFSC directory API and bank metadata (bank names, MICR bank codes): Razorpay IFSC (derived from RBI/NPCI lists; MIT code, data per their README); responses cached in `data/real/ifsc_api_cache.json`. Used live for branch/MICR lookups when online, bank-level checks only when offline.
- Final cheque evaluation: `eval/eval_cheque_verify.py` -> `data/real/eval_cheque_verify.json`. Certificates and PAN/Udyam layouts are rendered fictional data (`make_certs.py`); no real certificates are publicly available.
