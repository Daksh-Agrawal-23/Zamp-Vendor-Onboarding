# Design decisions

## The five calls that shape everything
1. **Rules decide, a model never approves.** Money decisions have to be explainable and repeatable. A model could help read a blurry document, but it should not be what approves a vendor.
2. **A wrong approval costs far more than a wrong hold.** An approved fraudulent vendor means payment fraud or a tax penalty; a good vendor held for a day costs a day. So the default is Pending, Reject only on definitive evidence, and anything that needs judgement goes to a person.
3. **Claims versus evidence.** What the vendor types is a claim. Documents and registries are evidence. I compare them field by field and show the result in one table. When the system cannot read something confidently it says so and asks for a better upload, rather than guessing.
4. **Fail safe.** A registry outage means Pending, never a pass. A missing document, a changed bank account or a cheque from another company never auto-approves. High-risk vendors need two different approvers. Every decision is written to a tamper-evident log.
5. **Say what is simulated.** The GST, PAN, bank and Udyam registries are simulated, because there is no public access. I used real public data (IFSC directory, MCA company records, OFAC list, cheque images) only to test the parts that can be tested. `docs/ROADBLOCKS.md` lists what only production access can fix.

## What the rules check (India)
GSTIN and PAN structure and check character; GSTIN-PAN-state consistency; registry status (cancelled is rejected, suspended is held); IFSC against the RBI directory and the declared bank; the cancelled cheque against the declared IFSC (printed code, MICR band, bank name, branch); account holder name against the legal name; sanctions and duplicate vendors; a changed bank account on an approved vendor (call-back required). Composition-scheme dealers are valid payees, so that is a note for AP, not a hold. US (EIN) and UK (VAT) get lighter checks.

## What I tested and what it showed
- **Cheques:** 154 images (112 labelled scans, 30 synthetic, 12 phone photos). The right bank claim was confirmed on 101 of 112 scans and 6 of 6 labelled photos. Every wrong-bank claim was caught. Every miss on a correct claim became a hold for a person, never an approval. Weakness: 87 of the scans are one Axis form.
- **Company names:** 18,500 realistic rewrites of real MCA company names (Pvt Ltd, M/s, abbreviations, word order): 99.9% matched. Of 716 near-identical but different real companies, 1 was wrongly matched.
- **GSTIN reading:** 98% on 90 invoice images with simulated scan damage (not real certificates), and no wrong GSTIN was ever accepted because each must pass its check character.
- **Rules engine:** zero false holds on 1,548 healthy vendor variants and all 3,032 injected defects caught. I wrote both sides of that test, so it proves the plumbing, not real-world accuracy.

## Known weaknesses
Registries are simulated. Sanctions screening is OFAC only and its recall on name variants is not measured. Name matching has no real labelled AP data behind it. The portal has a basic rate limit but no CAPTCHA. Demo credentials are on by default.

## What I would do next with real access
Plug a licensed GST/PAN/bank verification provider into the one adapter class (`Registries` in `engine.py`). Run in shadow mode on a few hundred historical vendors and compare with what the AP team decided. Then tune thresholds from that, not from my guesses.

## How I used AI
I used Claude as a coding assistant: it wrote most of the code and the synthetic test data, and it reviewed the app as a mock screener. The parts I decided are the problem framing, the claims-versus-evidence design, the default-to-Pending rule, which cases escalate versus reject, the starting thresholds (name match 85/60, sanctions 95, high-value 50 lakh), what to simulate, and which edge cases to show. I ran the code against public real-name and cheque data and kept the changes that the numbers supported. The tuned thresholds are guesses until there is real shadow-mode data. I can walk through any rule in `engine.py` and say why it is there.
