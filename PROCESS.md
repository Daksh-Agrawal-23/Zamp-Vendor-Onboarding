# The process, step by step

**Input:** a vendor submission (company details, GSTIN, PAN, bank account and IFSC, optional Udyam) plus uploaded documents (GST certificate, cancelled cheque, optionally PAN card and Udyam certificate). Vendors use the public portal; staff can also enter one.

**Output:** Approved, Pending (the vendor can fix it), Escalated (a person decides) or Rejected, one plain sentence saying why, a message back to the vendor, and, if approved, a profile the AP team needs (tax deduction hint, MSME terms, GST mode, when to re-verify).

| Stage | What happens | Example decision |
|---|---|---|
| 1. Intake | Required fields checked; a vendor with no GST registration is allowed | missing bank account: Pending |
| 2. Read documents | OCR, then a quality check; if unsure the reader abstains and asks for a clearer photo | blurry cheque: Pending, with tips |
| 3. Formats | GSTIN, PAN, IFSC structure and check characters; GSTIN, PAN and state must agree | GSTIN typo: Pending, with a suggested fix |
| 4. Registries (simulated) | GST status, PAN status, Udyam, company status | cancelled GSTIN: Rejected; registry down: Pending |
| 5. Claims vs evidence | Name against registry and cheque, cheque against declared IFSC, account number | cheque in another company's name: Escalated |
| 6. Screening | Sanctions list, duplicate vendors, changed bank details on an approved vendor | bank details changed: Escalated, call-back needed |
| 7. Decision | Highest-severity finding wins; two weak flags escalate; high-risk vendors need two approvers | none of the above: Approved |
| After | Vendor email, reminders on day 3 and 7, close on day 14, a review queue with reasons, an audit log | |

**Edge cases I chose, and why:** (1) a GSTIN typo, because it is the most common vendor mistake and should cost one email, not a rejection; (2) a cancelled cheque from another company, the classic payment-diversion pattern; (3) changed bank details on an already approved vendor, the other classic fraud; (4) a registry outage, to show we never approve because a check could not run. More scenarios are under "More scenarios" on the New vendor page.

**Assumptions I made:** India in depth; US and UK get format checks only and always go to a person; the GST, PAN, bank and Udyam registries are simulated because there is no public access; a vendor's typed details are claims, documents and registries are evidence.

**Where to find it in the code:** stages and rules are in `engine.py` (`run`, `RULES`); identifier and name logic in `validators.py`; document reading in `docread.py`; the web app in `app.py`.
