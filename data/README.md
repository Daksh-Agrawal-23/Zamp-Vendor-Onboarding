# Data used in this project

Everything is public or academic data. Nothing private, nothing scraped behind a login. Demo vendors are fictional.
Three groups: **stored here**, **linked (too big, fetch with `tools/fetch_data.py`)**, **kept local on purpose**.

## 1. Stored in this repo

| Path | What it is | Source / licence |
|---|---|---|
| `data/demo/`, `data/synth/` | Demo vendors, scenario files, synthetic vendors generated with a fixed seed | Mine (fictional) |
| `data/real/cheque_labels.json` | **Hand-made labels**: the true IFSC of 6 real phone/web cheque photos, read by eye, used to score cheque verification | Mine |
| `data/real/real_seed.json` | Real identifiers seeded into the registries, with a provenance block | Razorpay IFSC (public domain), GLEIF (CC0) |
| `data/real/name_calibration.json`, `mca_profile.json` | Thresholds and base rates I derived from 1.05M real MCA records | Derived from open government data |
| `data/real/banknames.json`, `banks_meta.json`, `ifsc_list.json`, `ifsc_api_cache.json` | RBI bank codes and IFSC existence list (260 banks, 183,214 branch codes) | Razorpay IFSC, derived from RBI lists, public domain |
| `data/real/raw/SDN.CSV.gz`, `ADD.CSV.gz`, `ALT.CSV.gz` | OFAC sanctions list with addresses and aliases, published 2026-11-19 | US Treasury, public |
| `data/real/raw/gleif_{in,us,gb}_all.json.gz` | 6,000 Indian, 1,600 US, 1,600 UK legal entities | GLEIF public API, CC0 |
| `data/real/raw/nse.csv`, `banks.json` | NSE listed-company list, RBI bank list | Public |
| `data/real/mca/sample_2000_rows.csv` | First 2,000 rows of the MCA master data (schema and sample) | data.gov.in open data |
| `data/real/hf/gst/*` | Ground truth for the 90 invoices, the 24 prompt-injection invoices, and my eval manifest (no images) | `Divya52/indian-gst-invoices`, CC-BY-4.0 |
| `data/real/eval_*.json`, `real_*.json` | Every evaluation result file (see `docs/EVIDENCE.md`) | Mine |
| `samples/invoices/` | 12 invoice images with ground truth | CC-BY-4.0, attribution inside |

## 2. Large public datasets (links, not copied)

| Dataset | Size | Licence | What it is | Used for | Needed by |
|---|---|---|---|---|---|
| [`Divya52/indian-gst-invoices`](https://huggingface.co/datasets/Divya52/indian-gst-invoices) | 29 MB images | CC-BY-4.0 | Synthetic Indian GST invoices (clean, scanned, phone-photo styles) plus a prompt-injection set, with ground-truth GSTIN | GSTIN reading accuracy by scan quality (88/90 end to end), image-quality gate, injection robustness | `eval/eval_docs.py`, `eval_quality.py` |
| [`arunchincheti/handwritten_and_cheques_dataset`](https://huggingface.co/datasets/arunchincheti/handwritten_and_cheques_dataset) | about 100 MB | Apache-2.0 | 300 dpi scans of Indian cheques from 4 banks, with IFSC labels | Cheque verification (four signals) on real scans | `eval/eval_cheque_verify.py` |
| [`jaganadhg/cheque-synthetic-images`](https://huggingface.co/datasets/jaganadhg/cheque-synthetic-images) | 91 MB | Apache-2.0 | 30 Indian cheque images with the IFSC box annotated | First IFSC extraction test (19/30 recovered and checksum-verified) | `eval/eval_docs.py` |
| MCA company and LLP master data, UP + Maharashtra (1,051,234 records: 854,324 CINs, 195,343 LLPINs) | 300 MB CSV | Open government data (data.gov.in) | Company name, CIN, status, class, registration date, address | Status base rates (26.8% not Active), CIN rules, name thresholds, address concentration | `eval/eval_names_real.py`, `eval_sanctions_real.py`, `analysis_mca.py` |
| [OFAC SDN list](https://www.treasury.gov/ofac/downloads/) | stored here | Public | Sanctions entries | Sanctions screening | engine |
| [GLEIF](https://api.gleif.org/api/v1/lei-records) | stored here | CC0 | Legal entity identifiers | Real GSTIN/CIN/name patterns | rules calibration |
| [Razorpay IFSC](https://github.com/razorpay/ifsc) | stored here | Public domain | RBI IFSC data (`https://ifsc.razorpay.com/<IFSC>`) | IFSC existence, bank check | engine |

Fetch the Hugging Face sets with `python tools/fetch_data.py` (needs `pip install huggingface_hub`). The MCA files are not auto-fetched: download "company master data" for Uttar Pradesh and Maharashtra from data.gov.in and save them as `data/real/mca/up_or_mh_A.csv` and `up_or_mh_B.csv` (the repo copy of the dataset is on my Hugging Face account; the link is in the README once published).

## 3. Kept local on purpose
- **12 real cheque photos** taken from public explainer web pages: they show real bank details, so I use them only for local testing and score them against `cheque_labels.json`. Results are in `docs/EVIDENCE.md`.
- **Full 300 MB MCA CSVs**: size. The profile derived from them is stored (`mca_profile.json`, `name_calibration.json`).
- **Real production data**: none was used.
