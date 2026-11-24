# The rules and why they exist

Rules version `2026.11.23`. 37 rules in `engine.py` (`RULES` table). No model decides anything: each rule is a deterministic check, and the outcome is the most severe outcome of any rule that fired (Rejected > Escalated > Pending > flag).

## Why the outcomes are what they are
- **Pending**: the vendor can fix it (typo, missing file, mismatch with a document). Default when unsure, because a good vendor held for a day costs a day, while a wrongly approved one can mean payment fraud or a tax penalty.
- **Escalated**: a person must decide (identity conflicts, look-alike names, sanctions hits, bank-account changes). The system will not guess on these.
- **Rejected**: only on definitive evidence, such as a cancelled registration. Never on a read error or a low-quality image.
- **Flag**: weak signals shown to the reviewer, never decisive on their own (for example the PAN 5th-letter hint, calibrated on real MCA data).
- **Fail safe**: a registry outage means Pending, never a pass. High-risk vendors need two different approvers. Every decision is written to a hash-chained audit log.
- **Claims vs evidence**: what the vendor types is a claim; documents and registries are evidence. Rules compare them field by field.

Several thresholds come from real data, not guesses: CIN, GSTIN and PAN formats checked on 3,000 real GSTINs and 1,878 CINs, name matching on 18,500 rewrites of real company names, address concentration and status base rates on 1.05 million MCA records. See [EVIDENCE.md](EVIDENCE.md) and [DATA_SOURCES.md](DATA_SOURCES.md).

## All rules

| ID | Outcome | What it checks | What the vendor is told |
|---|---|---|---|
| R01 | Pending | Required field or document missing | Please provide the missing item(s). |
| R02 | Pending | GSTIN pattern / state code invalid | Copy the 15-character GSTIN exactly from your GST registration certificate. |
| R03 | Pending | GSTIN check character wrong | The GSTIN looks mistyped (its built-in check digit fails). Re-copy it from your certificate. |
| R04 | Pending | PAN pattern invalid | A PAN has 5 letters, 4 digits and 1 letter (for example ABCDE1234F). |
| R05 | Escalated | PAN inside GSTIN differs from PAN submitted | The GSTIN and PAN you gave belong to different taxpayers. Check both against your certificates. |
| R06 | Pending | PAN holder type / initial does not fit the legal name | Please check the PAN and the legal name on it. |
| R07 | Pending | GSTIN state differs from declared state | Your GSTIN is registered in a different state from the one entered. Confirm the registered state. |
| R08 | Pending | IFSC invalid, unknown or retired bank | Please re-enter the IFSC from your cheque or bank statement. |
| R09 | Pending | IFSC bank differs from declared bank | The IFSC belongs to a different bank from the one entered. |
| R10 | Pending | Names differ across submission / documents / bank | Please make sure the legal name is identical on the form, certificate and bank account. |
| R11 | Escalated | Bank account already belongs to a different vendor | Our team will contact you. |
| R12 | Escalated | Duplicate or look-alike of an existing vendor | Our team will contact you. |
| R13 | Flag (informational) | Email domain looks unusual for a company | (internal; no vendor message) |
| R14 | Flag (informational) | Address is a PO box only | (internal; no vendor message) |
| R15 | Pending | Wrong document type or unreadable | Please upload the correct document, as a clear photo or scan. |
| R16 | Pending | GST registration not in good standing | The GST registry shows your registration as not active. Please check your GST status with your GST consultant or the GST portal, and share the corrected details. |
| R17 | Pending | PAN not operative | Your PAN is not operative (usually not linked to Aadhaar). Please fix this with the Income Tax department. |
| R18 | Pending | Udyam registration invalid / not found | Please check your Udyam number or remove the MSME claim. |
| R19 | Escalated | Sanctions / watch-list possible match | (internal; no vendor message) |
| R20 | Pending | Bank account verification failed or name differs | We could not confirm this account belongs to the legal name. Please check the account number and IFSC. |
| R21 | Pending | CIN structure / class inconsistent with name | Please re-check the CIN (21 characters) from your certificate of incorporation. |
| R22 | Rejected | Company not Active in MCA records | (internal; no vendor message) |
| R23 | Pending | CIN year inconsistent with incorporation date | The incorporation year in the CIN does not match your records. |
| R24 | Flag (informational) | Registered address shared by many unrelated vendors | (internal; no vendor message) |
| R25 | Pending | Document quality too low to read | Please upload a sharper, well-lit, flat photo or the original PDF. |
| R26 | Pending | Registry unavailable: not yet verified | One of the official registries is temporarily unreachable. No action is needed from you; we re-check automatically and will email you. |
| R27 | Escalated | Bank-detail change: call-back verification required | (internal; no vendor message) |
| R28 | Escalated | High-risk tier: human sign-off required | (internal; no vendor message) |
| R29 | Pending | US: EIN invalid | An EIN looks like 12-3456789. |
| R30 | Pending | UK: VAT number invalid | Please re-check your UK VAT number. |
| R31 | Pending | Cancelled cheque does not match declared bank/branch | Please upload a cancelled cheque from the account you declared, or correct the IFSC. |
| R32 | Pending | Account number on cheque differs from declared | The account number on the cheque differs from what you entered. Please check it, or upload the right cheque. |
| R33 | Pending | Udyam certificate number differs from declared | The Udyam number on your certificate differs from what you entered. Please correct it. |
| R34 | Escalated | Name mixes look-alike scripts | (internal; no vendor message) |
| R35 | Pending | Required document missing | Please upload the missing document(s): a GST registration certificate and a cancelled cheque are required before we can verify you. |
| R36 | Pending | GSTIN not found in the GST registry | We could not find this GSTIN in the GST registry. Please re-check the number against your GST certificate. |
| R37 | Escalated | Vendor says it is not GST-registered, but its PAN has a GST registration | (internal; no vendor message) |

Source of truth: `engine.py`. Per-rule tests: `tests/test_engine.py`; measured behaviour: `eval/eval_engine.py` (0 of 1,548 healthy variants wrongly held, 3,032 of 3,032 injected defects caught).
