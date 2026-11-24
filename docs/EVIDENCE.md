# Evidence: does the document reading actually work?

Short answer: yes, and this page shows real outputs, including where it fails. Nothing here is hard-coded: every table below was produced by running the code in this repository on files in this repository (or on public datasets listed in [DATA_SOURCES.md](DATA_SOURCES.md)). The raw results are in [`results/`](results) and `data/real/*.json`; the scripts that regenerate them are in [`eval/`](../eval).

**The honest limits first.** There are no public real GST certificates, so the test documents are (a) public synthetic invoices with known answers, with scan and phone-photo degradation added by the dataset authors, (b) real public cheque scans and photos, and (c) fictional certificates and cheques I rendered myself. I did not have real phone photos of real certificates. The government registries are simulated.

## 1. The reader on 12 public invoice images with known answers
These are the first four images of each quality tier (clean, scanned, phone photo) from the public `Divya52/indian-gst-invoices` dataset (CC-BY-4.0), copied to [`samples/invoices`](../samples/invoices) with their ground truth. Each invoice has two GSTINs (supplier and buyer). The reader was told the declared supplier GSTIN, as the web app is. Reproduce with `python tools/read_document.py gst_cert samples/invoices/<file> --expect <GSTIN>`.

| File | Quality | Layout | Known supplier GSTIN | GSTINs the reader found | Found | How | Time |
|---|---|---|---|---|---|---|---|
| `syn_syn_0_00922.png` | clean | classic | `33IZWCN4373L2Z3` | `33IZWCN4373L2Z3` | yes | exact | 0.7s |
| `syn_syn_0_01087.png` | clean | minimal | `24UKSPK0359J1ZB` | `24GIGPV8009U1Z5`, `24UKSPK0359J1ZB` | yes | multiple | 0.7s |
| `syn_syn_0_01204.png` | clean | classic | `33PXYCS3338E4ZB` | `08UVKPU0129U1Z3`, `33PXYCS3338E4ZB` | yes | multiple | 0.6s |
| `syn_syn_0_00827.png` | clean | handwritten | `09LPLFK1385I3ZQ` | `09FHWCW6482Q1ZA`, `09LPLFK1385I3ZQ` | yes | multiple | 2.1s |
| `syn_syn_0_01585.jpg` | scan | handwritten | `29HFZFC9494E9ZS` | `29HFZFC9494E9ZS` | yes | exact | 0.6s |
| `syn_syn_0_00024.jpg` | scan | minimal | `27PXMFW3368K3ZO` | `27PXMFW3368K3ZO`, `27VBHCK1536B4Z6` | yes | multiple | 4.6s |
| `syn_syn_0_01954.jpg` | scan | classic | `08IJTFZ2852S1Z4` | `08GTBCI2103N9Z9`, `08IJTFZ2852S1Z4` | yes | multiple | 0.7s |
| `syn_syn_0_00351.jpg` | scan | classic | `19JRSFG3108Z4ZW` | `19JRSFG3108Z4ZW`, `19NNEPB7925A2ZY` | yes | multiple | 2.1s |
| `syn_syn_0_01028.jpg` | photo | minimal | `36WFKCF7712V4ZP` | `36WFKCF7712V4ZP` | yes | exact+rapid-raw | 12.6s |
| `syn_syn_0_00630.jpg` | photo | handwritten | `08AFQPF5921K2Z2` | `08AFQPF5921K2Z2`, `24VDEPA6915T2ZM` | yes | multiple | 0.7s |
| `syn_syn_0_01963.jpg` | photo | thermal | `24OKOCS2610S1ZW` | `24IHYPN7523G1ZO`, `24OKOCS2610S1ZW` | yes | multiple | 2.2s |
| `syn_syn_0_01253.jpg` | photo | classic | `29BMXCD8118S1ZM` | `09FAWFB1456M4ZK`, `29BMXCD8118S1ZM` | yes | multiple | 8.8s |

**12 of 12** found.

Times include the heavier readers on phone photos: the 12.6 s and 8.8 s rows are photos that needed the second OCR engine.

## 2. The same reader on all 90 evaluation invoices
| Quality | Declared GSTIN found | 
|---|---|
| clean | 29 / 29 |
| scan | 23 / 23 |
| phone photo (simulated degradation) | 36 / 38 |
| **all** | **88 / 90** |

Per-image rows: [`results/app_reader_90_invoices.json`](results/app_reader_90_invoices.json). For the two photos where it did not find the declared GSTIN, the reader returns what it did see (or nothing), the declared GSTIN does not match, and the vendor is asked to upload a clearer photo. In one of the 90 the reader also returned a third GSTIN that is neither the supplier's nor the buyer's. That cannot cause an approval, because approval needs the declared GSTIN to be present and to pass the registry check, but it is a reminder that OCR is imperfect, which is why every value is also checksum-validated.

**How the reader got here** (all on the same 90 images, from [`results/eval_quality_rows.json`](results/eval_quality_rows.json)):

| Step | GSTIN found | Phone photos only |
|---|---|---|
| Tesseract on the page | 71% | 42% |
| + normalisation and image preparation | 74% | 50% |
| + RapidOCR second engine | 98% | 95% |

The first version of the reader (Tesseract only) found 67% of GSTINs; that is the baseline I started from. No wrong GSTIN was ever accepted, because every value must pass the check character.

**A bug I found while preparing this page.** The scoring script above lets the pipeline keep trying until it finds the right GSTIN, but the app's reader used to stop at the first valid GSTIN it found, which on an invoice can be the buyer's. On the 18 sample images I first tried, 3 were missed that way. The fix is that the app passes the declared GSTIN to the reader (`expect`), which keeps escalating until it has seen it. Re-scoring the app's own reader gave the 88 of 90 above.

## 3. The demo documents: what the reader sees versus what was typed
Each prepared scenario has a GST certificate and a cancelled cheque that I rendered. The reader was run on each and the result compared with what is typed on the form. The disagreements are exactly the scenarios' designed defects, found by the reader, not looked up:

| Scenario | Document | Reader result | Typed on the form |
|---|---|---|---|
| happy | GST certificate | 29UNNCM2011P1ZS (warn) | 29UNNCM2011P1ZS |
| happy | Cancelled cheque | IFSC KKBK0RTGSMI (repaired) | KKBK0RTGSMI |
| typo | GST certificate | 09JKKCA2056S1Z7 (warn) | O9JKKCA2056S1Z7 |
| typo | Cancelled cheque | IFSC UTIB0000248 (exact) | UTIB0000248 |
| photo | GST certificate | 07PKXCS3906H1ZW (poor) | 07PKXCS3906H1ZW |
| photo | Cancelled cheque | IFSC HDFC0999999 (exact) | HDFC0999999 |
| blur | GST certificate | abstained:  (poor) | 33WCFCB3122Y1ZJ |
| blur | Cancelled cheque | IFSC YESB0000001 (repaired) | YESB0000001 |
| cancelled | GST certificate | 08AGHFF2492C1Z8 (warn) | 08AGHFF2492C1Z8 |
| cancelled | Cancelled cheque | IFSC BARB0TREASU (repaired) | BARB0TREASU |
| third | GST certificate | 06YPEFK6436P1ZC (warn) | 06YPEFK6436P1ZC |
| third | Cancelled cheque | IFSC HDFC0999999 (exact) | HDFC0999999 |
| bankchange | GST certificate | 08CFBFK0174K1Z1 (warn) | 08CFBFK0174K1Z1 |
| bankchange | Cancelled cheque | IFSC HDFC0999999 (exact) | HDFC0999999 |
| retired | GST certificate | 36HESCC0655T1ZC (warn) | 36HESCC0655T1ZC |
| retired | Cancelled cheque | IFSC KKBK0RTGSMI (repaired) | SYNB0000001 |
| outage | GST certificate | 08VHCCA7194H1ZI (warn) | 08VHCCA7194H1ZI |
| outage | Cancelled cheque | IFSC UTIB0000248 (exact) | UTIB0000248 |


- **typo**: the form has `O9JKKCA2056S1Z7` (letter O); the document says `09JKKCA2056S1Z7`. The reader found the document's value, the check digit on the typed one fails, and the vendor is told what to re-copy.
- **blur**: the photo is too blurry, so the reader **abstains** and the vendor is asked for a clearer photo. It does not guess.
- **happy and others**: the cheque prints `KKBK0RTGSMI`, OCR reads the letter O for zero, and the repair step corrects it against the RBI list ("repaired").
- **retired**: the form declares an IFSC of a merged bank (`SYNB0000001`), while the cheque shows another code, so the case is held for the vendor to fix.

## 4. Real cheques
- **Real scans** (112 labelled scans of 4 banks, Axis, ICICI, Canara and Syndicate): the right bank claim was confirmed on 101 of 112 scans in the full evaluation and on 6 of 6 labelled real photos; **every wrong-bank claim was caught**; every miss on a correct claim became a hold for a person, never an approval. Caveat: 87 of the scans are one Axis form.
- **Reading the IFSC directly is the weak part.** On 12 real cheque photos from the public web, the printed code was verified against the RBI list on only 4 of 12 with either OCR engine: some print an old or merged-bank code that no longer exists (Syndicate Bank merged into Canara, so its codes have no live branches), some are low resolution, some are rotated. This is why cheques are verified against the claimed bank with four signals ([how](HOW_DOCUMENTS_ARE_READ.md)) instead of relying on the printed code.
- **30 synthetic cheques with the IFSC box annotated:** 19 of 30 recovered and verified.

## 5. Other measurements on real public data
| Test | Data | Result |
|---|---|---|
| Identifier rules on real identifiers | 3,000 real GSTINs and 1,878 real CINs (GLEIF public records) | 2,998 / 3,000 GSTINs and 1,878 / 1,878 CINs pass; the two failures are real data-entry errors |
| MCA status base rate | 1,051,234 real company and LLP records (UP and Maharashtra) | 26.8% are not Active (240,474 struck off), so a company-status check is high value |
| Company-name matching | 18,500 realistic rewrites of real MCA names (Pvt Ltd, M/s, abbreviations, word order) | 99.9% matched |
| Look-alike names | 716 near-identical but different real companies | 1 wrongly matched |
| Names are not identities | MCA records | 10.2% of real companies have a different real company scoring 85 or more on name, so name score alone cannot decide "same vendor" |
| Sanctions screening | 12,000 real names vs the real OFAC SDN list (19,599 records) | at the chosen threshold of 95: 3 hits (GLEIF), 0 (MCA), all single-word personal names, which are logged but not escalated alone |
| Prompt injection | 24 invoices with hidden instructions | 0 decisions changed, 0 foreign GSTINs accepted, supplier GSTIN still read on 22 / 24 |
| Decision engine | 172 healthy vendors x 8 benign variations; 15 injected defect types x about 170 vendors | 0 / 1,548 wrongly held; 3,032 / 3,032 defects caught by the intended rule. I wrote both sides, so this shows the plumbing is right, not real-world accuracy |

## 6. What the real data changed in the rules
Findings that changed the code (full list in [DATA_SOURCES.md](DATA_SOURCES.md)):
- A rule for a Telangana state-code mismatch (GST 36 against region TS) would have wrongly flagged real vendors; fixed.
- The CIN check rejected 0.5% of real CINs because a Nidhi company class was missing; all 14 observed class codes are now accepted.
- "Named Limited but class PTC" is common (37,525 real private companies) and was wrongly flagged; only the reverse is kept, at a 0.18% false-flag rate.
- Name handling for "P LTD" (766 names), the "M/S" prefix and names made only of suffix words was wrong; fixed.
- The PAN 5th-letter check matched 75% of real entities at first; calibrated to 87% by skipping business names under personal PANs, and it stays a low-weight hint.
- A merged bank leaves an IFSC with no live branches: that is a vendor-fixable case, not fraud.

## 7. Reproduce
```bash
python tools/run_all_tests.py                      # 7 test files, includes the reader on the demo documents
python eval/eval_quality.py                        # GSTIN reading on 90 invoices (needs the dataset, see DATA_SOURCES.md)
python eval/eval_cheque_verify.py                  # cheque verification
python eval/eval_names_real.py                     # company-name matching on real MCA names
python eval/eval_sanctions_real.py                 # sanctions on real names
python eval/eval_injection.py                      # hostile text in invoices
python eval/eval_engine.py                         # labelled synthetic vendors, 15 defect types
```
The large public datasets (MCA records, the invoice and cheque images) are not stored in this repository; [DATA_SOURCES.md](DATA_SOURCES.md) lists where each came from and its licence. The small result files they produced are included.
