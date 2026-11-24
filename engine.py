"""The decision engine: takes one vendor submission and returns Approved / Pending / Escalated / Rejected with reasons.

How a run goes (each stage reports to the live run view and the audit log):
  intake -> read documents -> check formats -> look up registries -> compare claims with evidence -> screen -> decide

The rules I settled on, and why:
  * Rules decide, no model. A finance person must be able to see why, and get the same answer twice.
  * Default is Pending (the vendor can fix it). Reject only when the evidence is definitive, e.g. the registry says the GSTIN is cancelled.
  * Escalate (a person decides) when judgement is needed, e.g. the cheque is in another company's name.
  * A registry being down is Pending. We never approve because a check could not run.
  * The paid bank check runs last, and only if every cheaper check is clean.
Outcomes used below: P = pending, E = escalate, R = reject, F = weak flag (one alone is ignored, two or more escalate).

Thresholds (name match 85 / 60, sanctions 95, high-value 50 lakh) are my starting guesses. With real access I would tune them
from shadow-mode data, not keep them.
"""

import hashlib, json, os, re, time
import validators as V

HERE = os.path.dirname(__file__)
P, E, R, F_ = "P", "E", "R", "F"
PRECEDENCE = {R: 4, E: 3, P: 2, F_: 1}

# id -> (outcome, title, vendor-facing fix).  Single source of truth, mirrored in the spec.
RULES = {
    "R01": (P, "Required field or document missing", "Please provide the missing item(s)."),
    "R02": (
        P,
        "GSTIN pattern / state code invalid",
        "Copy the 15-character GSTIN exactly from your GST registration certificate.",
    ),
    "R03": (
        P,
        "GSTIN check character wrong",
        "The GSTIN looks mistyped (its built-in check digit fails). Re-copy it from your certificate.",
    ),
    "R04": (P, "PAN pattern invalid", "A PAN has 5 letters, 4 digits and 1 letter (for example ABCDE1234F)."),
    "R05": (
        E,
        "PAN inside GSTIN differs from PAN submitted",
        "The GSTIN and PAN you gave belong to different taxpayers. Check both against your certificates.",
    ),
    "R06": (
        P,
        "PAN holder type / initial does not fit the legal name",
        "Please check the PAN and the legal name on it.",
    ),
    "R07": (
        P,
        "GSTIN state differs from declared state",
        "Your GSTIN is registered in a different state from the one entered. Confirm the registered state.",
    ),
    "R34": (E, "Name mixes look-alike scripts", ""),
    "R33": (
        P,
        "Udyam certificate number differs from declared",
        "The Udyam number on your certificate differs from what you entered. Please correct it.",
    ),
    "R31": (
        P,
        "Cancelled cheque does not match declared bank/branch",
        "Please upload a cancelled cheque from the account you declared, or correct the IFSC.",
    ),
    "R32": (
        P,
        "Account number on cheque differs from declared",
        "The account number on the cheque differs from what you entered. Please check it, or upload the right cheque.",
    ),
    "R08": (
        P,
        "IFSC invalid, unknown or retired bank",
        "Please re-enter the IFSC from your cheque or bank statement.",
    ),
    "R09": (
        P,
        "IFSC bank differs from declared bank",
        "The IFSC belongs to a different bank from the one entered.",
    ),
    "R10": (
        P,
        "Names differ across submission / documents / bank",
        "Please make sure the legal name is identical on the form, certificate and bank account.",
    ),
    "R11": (E, "Bank account already belongs to a different vendor", "Our team will contact you."),
    "R12": (E, "Duplicate or look-alike of an existing vendor", "Our team will contact you."),
    "R13": (F_, "Email domain looks unusual for a company", ""),
    "R14": (F_, "Address is a PO box only", ""),
    "R15": (
        P,
        "Wrong document type or unreadable",
        "Please upload the correct document, as a clear photo or scan.",
    ),
    "R16": (
        P,
        "GST registration not in good standing",
        "The GST registry shows your registration as not active. Please check your GST status with your GST consultant or the GST portal, and share the corrected details.",
    ),
    "R17": (
        P,
        "PAN not operative",
        "Your PAN is not operative (usually not linked to Aadhaar). Please fix this with the Income Tax department.",
    ),
    "R18": (
        P,
        "Udyam registration invalid / not found",
        "Please check your Udyam number or remove the MSME claim.",
    ),
    "R19": (E, "Sanctions / watch-list possible match", ""),
    "R20": (
        P,
        "Bank account verification failed or name differs",
        "We could not confirm this account belongs to the legal name. Please check the account number and IFSC.",
    ),
    "R21": (
        P,
        "CIN structure / class inconsistent with name",
        "Please re-check the CIN (21 characters) from your certificate of incorporation.",
    ),
    "R22": (R, "Company not Active in MCA records", ""),
    "R23": (
        P,
        "CIN year inconsistent with incorporation date",
        "The incorporation year in the CIN does not match your records.",
    ),
    "R24": (F_, "Registered address shared by many unrelated vendors", ""),
    "R25": (
        P,
        "Document quality too low to read",
        "Please upload a sharper, well-lit, flat photo or the original PDF.",
    ),
    "R35": (
        P,
        "Required document missing",
        "Please upload the missing document(s): a GST registration certificate and a cancelled cheque are required before we can verify you.",
    ),
    "R36": (
        P,
        "GSTIN not found in the GST registry",
        "We could not find this GSTIN in the GST registry. Please re-check the number against your GST certificate.",
    ),
    "R37": (E, "Vendor says it is not GST-registered, but its PAN has a GST registration", ""),
    "R26": (
        P,
        "Registry unavailable: not yet verified",
        "One of the official registries is temporarily unreachable. No action is needed from you; we re-check automatically and will email you.",
    ),
    "R27": (E, "Bank-detail change: call-back verification required", ""),
    "R28": (E, "High-risk tier: human sign-off required", ""),
    "R29": (P, "US: EIN invalid", "An EIN looks like 12-3456789."),
    "R30": (P, "UK: VAT number invalid", "Please re-check your UK VAT number."),
}
BANK_ALIAS = {
    "STATE BANK": ("SBI",),
    "PUNJAB NATIONAL": ("PNB",),
    "BARODA": ("BOB",),
    "KOTAK": ("KMB",),
    "CANARA": ("CNRB",),
    "UNION BANK": ("UBI",),
    "BANK OF INDIA": ("BOI",),
    "INDIAN OVERSEAS": ("IOB",),
    "CENTRAL BANK": ("CBI",),
    "INDUSIND": ("IIB",),
}
BANK_PREFIX = {
    "KKBK": "KOTAK",
    "UTIB": "AXIS",
    "HDFC": "HDFC",
    "ICIC": "ICICI",
    "SBIN": "STATE BANK",
    "BARB": "BARODA",
    "PUNB": "PUNJAB NATIONAL",
    "YESB": "YES",
    "IDIB": "INDIAN BANK",
    "CNRB": "CANARA",
    "UBIN": "UNION BANK",
    "BKID": "BANK OF INDIA",
}
FREE_MAIL = {
    "gmail.com",
    "yahoo.com",
    "yahoo.in",
    "outlook.com",
    "hotmail.com",
    "rediffmail.com",
    "proton.me",
}
COST = {"cheap": 0, "paid": 1}  # paid = bank penny-drop (simulated); see engine run for ordering


def _load(name, default):
    try:
        return json.load(open(os.path.join(HERE, "data", name)))
    except OSError:
        return default


class Registries:
    OVERRIDES = (
        {}
    )  # demo-only: {gstin: {field: value}} applied on top of the registry (simulates drift after onboarding)
    """Registries over the synthetic vendor universe, plus real data where available (real MCA UP+MH, RBI IFSC list, OFAC SDN).
    GST / PAN / Udyam / bank verification are SIMULATED. `down` simulates an outage of: gst, pan, mca, sanctions, bank, udyam."""

    def __init__(self, vendors=None, sanctions=None, mca=None, down=()):
        self.v = vendors if vendors is not None else _load("synth/registry.json", [])
        self.by_gstin = {x["gstin"]: x for x in self.v if x.get("gstin")}
        self.by_pan = {x["pan"]: x for x in self.v if x.get("pan")}
        self.by_udyam = {x["udyam"]: x for x in self.v if x.get("udyam")}
        self.by_acct = {(x["ifsc"], x["account"]): x for x in self.v if x.get("account")}
        self.sanctions = sanctions if sanctions is not None else _load("synth/sanctions_index.json", [])
        self._sn = [(V.normalise_name(s["name"]), s) for s in self.sanctions]
        self._names = [x for x, _ in self._sn]
        self.mca = mca or {}
        self.down = set(down)
        self.paid_calls = 0

    def _chk(self, svc):
        if svc in self.down:
            raise TimeoutError(f"{svc.upper()} service timeout")

    def gst_lookup(self, gstin):
        self._chk("gst")
        r = self.by_gstin.get(gstin)
        return dict(r, **self.OVERRIDES[gstin]) if r and gstin in self.OVERRIDES else r

    def pan_lookup(self, pan):
        self._chk("pan")
        return self.by_pan.get(pan)

    def udyam_lookup(self, u):
        self._chk("udyam")
        return self.by_udyam.get(u)

    def mca_lookup(self, cin):
        self._chk("mca")
        return self.mca.get(cin)

    def bank_verify(self, ifsc, account):
        """Penny-drop: the bank returns the beneficiary name for (ifsc, account). PAID call (simulated)."""
        self._chk("bank")
        self.paid_calls += 1
        x = self.by_acct.get((ifsc, account))
        return None if not x else x["legal_name"].upper()[:32]  # banks truncate / upper-case names

    def sanctions_hits(self, name, threshold=95):
        self._chk("sanctions")
        n = V.normalise_name(name)
        if not n or (len(n.split()) < 2 and len(n) < 8):
            return []  # one short word collides with real people (3/6000 real names)
        from rapidfuzz import process, fuzz

        res = process.extract(n, self._names, scorer=fuzz.ratio, score_cutoff=threshold, limit=5)
        return [self._sn[i][1] for _, _, i in res]


RULES_VERSION = "2026.11.23"
GENESIS = "0" * 64


def _h(prev, stage, event, data):
    return hashlib.sha256(
        (prev + json.dumps([stage, event, data], sort_keys=True, default=str)).encode()
    ).hexdigest()


class Audit:
    """Append-only SHA-256 hash chain: each entry commits to the previous one, so edits are detectable. Head hashes are also written to an
    external append-only anchor file (see app.anchor) so a DB-only attacker cannot silently recompute the chain.
    """

    def __init__(self):
        self.entries, self._prev = [], GENESIS

    def add(self, stage, event, **data):
        e = dict(t=round(time.time(), 3), stage=stage, event=event, data=data, prev=self._prev)
        e["hash"] = _h(self._prev, stage, event, data)
        self._prev = e["hash"]
        self.entries.append(e)
        return e

    @staticmethod
    def append(entries, stage, event, **data):
        """Add a later entry (reviewer decision, status change) to an existing chain."""
        prev = entries[-1]["hash"] if entries else GENESIS
        e = dict(
            t=round(time.time(), 3),
            stage=stage,
            event=event,
            data=data,
            prev=prev,
            hash=_h(prev, stage, event, data),
        )
        entries.append(e)
        return e

    @staticmethod
    def verify(entries):
        prev = GENESIS
        for e in entries:
            if e["prev"] != prev or e["hash"] != _h(prev, e["stage"], e["event"], e["data"]):
                return False
            prev = e["hash"]
        return True


def risk_tier(sub):
    if (
        sub.get("expected_annual_value") is None
        and not sub.get("bank_change")
        and sub.get("country", "IN") == "IN"
    ):
        return "Standard"  # vendor-submitted: value unknown until procurement sets it
    amt = float(sub.get("expected_annual_value") or 0)
    if sub.get("bank_change") or sub.get("country", "IN") != "IN" or amt > 5_000_000:
        return "High"
    return "Low" if amt < 500_000 else "Standard"


def _bank_name_score(declared, beneficiary):
    """Banks upper-case and TRUNCATE beneficiary names (commonly ~32 chars, found on 2/172 healthy vendors): treat a prefix as a match."""
    a, b = V.normalise_name(declared).replace(" ", ""), V.normalise_name(beneficiary).replace(" ", "")
    if len((beneficiary or "").strip()) >= 30 and len(b) >= 10 and (a.startswith(b) or b.startswith(a)):
        return 100  # only a plausibly truncated (~32 char) beneficiary counts as a prefix match
    return V.name_score(declared, beneficiary)


def _mask(s):
    s = s or ""
    return s if len(s) <= 4 else "*" * (len(s) - 4) + s[-4:]


# verification policy: how long each kind of evidence stays valid, and how strong it is
EVIDENCE_TIER = {
    "registry": "T1",
    "bank": "T1",
    "document": "T2",
    "cheque": "T2",
    "sanctions": "T2",
    "declared": "T4",
}  # T1 authoritative source, T2 document read, T4 self-declared
REVERIFY_DAYS = {"gstin": 90, "pan": 365, "cin": 180, "udyam": 365, "account": 365}


def build_profile(sub, F, M, tier, status):
    """Everything AP needs to set the vendor up correctly, plus when each fact was verified and when it must be re-verified."""
    rules = {f["rule"]: f for f in F}
    now = time.time()
    tds = (
        "20% (higher rate: PAN not operative / not linked to Aadhaar)"
        if "R17" in rules
        else "Standard rate for the payment type (PAN operative)"
    )
    msme = None
    cls = str(((sub.get("docs") or {}).get("udyam_cert") or {}).get("enterprise_class") or "").lower()
    if sub.get("udyam") and "R18" not in rules and "R26" not in rules:
        if cls.startswith("medium"):
            msme = "Medium enterprise: the 45-day MSME payment rule does not apply"
        else:
            msme = (
                "Micro/small enterprise: pay within 45 days (MSMED Act s.15; 15 days if no written agreement)"
                + ("" if cls else " (confirm class on the Udyam certificate; medium enterprises are exempt)")
            )
    gst_mode = (
        "Not registered for GST: GST must not be charged on its invoices (ask the tax team whether reverse charge applies)"
        if sub.get("no_gst") and not sub.get("gstin")
        else (
            "Composition dealer: issues bills of supply, cannot charge GST, no input tax credit for us"
            if "composition" in str(M.get("gstin", {}).get("registry", "")).lower()
            or (((sub.get("docs") or {}).get("gst_cert") or {}).get("composition"))
            else "Regular GST registrant (input credit allowed)"
        )
    )
    ver = {}
    for field, srcs in M.items():
        srcs = {
            k: v for k, v in srcs.items() if not str(v).startswith("not run")
        }  # a check that did not run is not evidence
        tiers = [EVIDENCE_TIER.get(k) for k in srcs if k in EVIDENCE_TIER]
        ver[field] = dict(
            best_evidence=min(tiers) if tiers else "T4",
            sources=[k for k in srcs if k in EVIDENCE_TIER],
            reverify_by=(
                time.strftime("%Y-%m-%d", time.localtime(now + REVERIFY_DAYS.get(field, 365) * 86400))
                if "registry" in srcs or "bank" in srcs
                else None
            ),
        )
    return dict(
        status=status,
        risk_tier=tier,
        tds=tds,
        msme_terms=msme,
        gst_mode=gst_mode,
        verified_as_of=time.strftime("%Y-%m-%d %H:%M", time.localtime(now)),
        evidence=ver,
        flags=[f["rule"] + ": " + f["detail"] for f in F if f["outcome"] == F_],
        rules_version=RULES_VERSION,
        payment_hold=status != "Approved",
    )


def run(sub, reg: Registries, emit=lambda stage, msg: None, existing=None):
    """Run one submission through the stages below, in order, and return the decision.

    Stages (the banner comments mark each one): intake, documents, format, registry, crosscheck,
    screening, the paid bank check (only if everything cheaper is clean), decision.
    `flag()` records a finding; the decision stage picks the strongest one. `existing` is the
    already-approved vendor record, used to spot changed bank details.
    """
    _T0 = time.time()
    A = Audit()
    F = []
    M = {}  # audit, findings, evidence matrix

    def flag(rule, detail, field=None, outcome=None):
        if any(f["rule"] == rule and f["field"] == field for f in F):
            return
        o = outcome or RULES[rule][0]
        F.append(
            dict(rule=rule, outcome=o, title=RULES[rule][1], detail=detail, field=field, fix=RULES[rule][2])
        )
        A.add("check", rule, detail=detail, field=field, outcome=o)
        emit(
            "finding",
            {
                "P": "Needs a fix from the vendor",
                "E": "Needs a person to review",
                "R": "Cannot be approved",
                "F": "Noted (weak signal)",
            }.get(o, o)
            + f": {detail}",
        )

    def ev(field, **kw):
        M.setdefault(field, {}).update({k: v for k, v in kw.items() if v not in (None, "")})

    def stage(n, msg):
        emit(n, msg)
        A.add(n, "stage", msg=msg)

    country = (sub.get("country") or "IN").upper()
    name = (sub.get("legal_name") or "").strip()
    docs = sub.get("docs") or {}
    if (
        sub.get("docs_required") and (sub.get("country") or "IN").upper() == "IN"
    ):  # evidence floor: never auto-approve on typed claims alone
        miss = [
            n
            for k, n in (("gst_cert", "GST certificate"), ("cheque", "cancelled cheque"))
            if not docs.get(k) and not (k == "gst_cert" and sub.get("no_gst"))
        ]
        if miss:
            flag("R35", "no " + " or ".join(miss) + " uploaded", "documents")
    gstin = (sub.get("gstin") or "").strip().upper()
    pan = (sub.get("pan") or "").strip().upper()
    ifsc = (sub.get("ifsc") or "").strip().upper()
    cin = (sub.get("cin") or "").strip().upper()
    account = (sub.get("account") or "").strip()
    ev("legal_name", declared=name)
    ev("gstin", declared=gstin)
    ev("pan", declared=pan)
    ev("ifsc", declared=ifsc)
    ev("account", declared=_mask(account))
    ev("state", declared=sub.get("state"))
    stage("intake", f"Received submission for '{name or '(no name)'}' ({country})")
    A.add(
        "intake",
        "rules_version",
        version=RULES_VERSION,
        thresholds=dict(name_pass=85, name_review=60, sanctions=95, high_value=5_000_000),
    )
    A.add(
        "intake",
        "received",
        masked={k: _mask(str(sub.get(k) or "")) for k in ("pan", "gstin", "account", "cin")},
    )
    need = ["legal_name", "country"] + (
        ["pan", "ifsc", "account"] + ([] if sub.get("no_gst") else ["gstin"]) if country == "IN" else []
    )
    for k in need:
        if not str(sub.get(k) or "").strip():
            flag("R01", f"{k} is required", k)

    # ---- documents (reading already done by docread; here we judge) ------------------------------------
    stage("documents", "Judging document reads")
    for doc, d in docs.items():
        q = d.get("quality") or {}
        if d.get("error"):
            flag("R25", d["error"], doc)
        elif d.get("wrong_type"):
            flag("R15", f"{doc}: this does not look like a {doc.replace('_', ' ')}", doc)
        elif d.get("abstained"):
            nice = {
                "gst_cert": "GST certificate",
                "cheque": "cancelled cheque",
                "pan_card": "PAN card",
                "udyam_cert": "Udyam certificate",
            }.get(doc, doc)
            flag(
                "R25",
                f"Your {nice} could not be read. "
                + (" ".join(q.get("reasons", [])[:2]) or "Please upload a clearer image."),
                doc,
            )
        elif q.get("reasons"):
            A.add("documents", "quality_note", doc=doc, reasons=q["reasons"])
        if doc == "gst_cert" and not d.get("abstained") and d.get("doctype") == "invoice-like":
            flag(
                "R15",
                "an invoice was uploaded where the GST registration certificate (Form GST REG-06) is required",
                doc,
            )

    # ---- format checks ---------------------------------------------------------------------------------
    stage("format", "Validating identifiers")
    g_ok = p_ok = False
    if country == "IN":
        if sub.get("no_gst") and not gstin:
            emit(
                "finding",
                "Vendor declares it is not registered for GST; checking that its PAN really has no GST registration",
            )
        if gstin:
            g_ok, why = V.validate_gstin(gstin)
            if g_ok:
                emit("finding", f"OK: GSTIN {gstin} has a valid format and check character")
            if not g_ok:
                fix = V.suggest_gstin_fix(gstin)
                flag(
                    "R03" if "check character" in why else "R02",
                    why + (f"; did you mean {fix}?" if fix else ""),
                    "gstin",
                )
        if pan:
            p_ok, why = V.validate_pan(pan)
            if not p_ok:
                flag("R04", why, "pan")
        if g_ok and p_ok and not V.gstin_pan_consistent(gstin, pan):
            flag("R05", f"GSTIN embeds PAN {V.pan_from_gstin(gstin)} but PAN given is {pan}", "pan")
        if p_ok and name and V.pan_name_hint(pan, name) is False:
            flag("R06", "PAN holder type / initial does not fit the legal name", "pan")
        if g_ok and sub.get("state") and not V.gstin_state_matches(gstin, sub["state"]):
            flag("R07", "GSTIN state differs from declared state", "state")
        if ifsc:
            st = V.ifsc_status(ifsc)
            if st in (
                "unknown_branch",
                "unknown_bank",
            ):  # our bundled list may be older than the RBI directory: ask the live directory before blaming the vendor
                try:
                    import cheque_verify as CV

                    rec_ = CV.lookup(ifsc)
                    if rec_ and not rec_.get("_missing") and rec_.get("IFSC") == ifsc:
                        st = "ok"
                except Exception:
                    pass
            ev("ifsc", registry=st)
            if st in ("bad_format", "unknown_bank", "unknown_branch", "retired_bank"):
                flag(
                    "R08",
                    {
                        "bad_format": "IFSC format is wrong",
                        "unknown_bank": "bank code not recognised",
                        "unknown_branch": "branch code not found for this bank",
                        "retired_bank": "this bank has merged; use the new bank's IFSC",
                    }[st],
                    "ifsc",
                )
            elif (
                sub.get("bank")
                and BANK_PREFIX.get(ifsc[:4])
                and BANK_PREFIX[ifsc[:4]] not in sub["bank"].upper()
                and not any(
                    re.search(r"\b" + al + r"\b", sub["bank"].upper())
                    for al in BANK_ALIAS.get(BANK_PREFIX[ifsc[:4]], ())
                )
            ):
                flag(
                    "R09",
                    f"IFSC {ifsc[:4]} is {BANK_PREFIX[ifsc[:4]].title()} but bank entered is '{sub['bank']}'",
                    "ifsc",
                )
        if cin:
            ok, why = V.validate_cin(cin)
            if not ok:
                flag("R21", why, "cin")
            elif V.cin_name_consistent(cin, name) is False:
                flag("R21", "company class in CIN is not consistent with a 'Private Limited' name", "cin")
        if sub.get("udyam") and not re.match(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$", sub["udyam"].strip().upper()):
            flag("R18", "Udyam number format is wrong (UDYAM-XX-00-0000000)", "udyam")
    elif country == "US":
        ok, why = V.validate_ein(sub.get("ein") or "")
        if not ok:
            flag("R29", why, "ein")
    elif country == "GB":
        ok, why = V.validate_uk_vat(sub.get("vat") or "")
        if not ok:
            flag("R30", why, "vat")
    if V.has_homoglyphs(name):
        flag("R34", "legal name mixes Latin letters with look-alike Cyrillic/Greek characters", "legal_name")
    email = (sub.get("email") or "").strip().lower()
    if (
        email
        and "@" in email
        and country == "IN"
        and ("private limited" in name.lower() or "llp" in name.lower() or "limited" in name.lower())
    ):
        if email.split("@")[-1] in FREE_MAIL:
            flag("R13", f"company vendor uses free webmail ({email.split('@')[-1]})", "email")
    if re.search(r"\b(p\.?\s?o\.?\s?box|post box|post office box)\b", (sub.get("address") or "").lower()):
        flag("R14", "address is a PO box", "address")

    # ---- registries ------------------------------------------------------------------------------------
    stage("registry", "Checking registries")
    rec = None

    def outage(e, field, what):
        flag("R26", f"{e}; {what} not verified yet", field)

    if country == "IN":
        if g_ok:
            try:
                rec = reg.gst_lookup(gstin)
                if rec is None:
                    flag(
                        "R36",
                        "GSTIN passes the checksum but is not in the GST registry (typo or wrong number)",
                        "gstin",
                    )
                else:
                    ev(
                        "gstin",
                        registry=f"{rec['gst_status']}"
                        + (", composition" if rec.get("gst_composition") else ""),
                    )
                    emit(
                        "finding",
                        f"OK: GST registry says {rec['gst_status']}, registered name \"{rec['legal_name']}\"",
                    )
                    ev("legal_name", registry=rec["legal_name"])
                    if rec["gst_status"] == "Cancelled":
                        flag(
                            "R16", "GSTIN status is Cancelled: cannot legally charge GST", "gstin", outcome=R
                        )
                    elif rec["gst_status"] == "Suspended":
                        flag("R16", "GSTIN status is Suspended", "gstin")
                    # composition-scheme dealers are legitimate payees: recorded in the AP profile (bill of supply, no ITC), not a hold
                    sc = V.name_score(name, rec["legal_name"])
                    band = V.name_band(sc)
                    f1, f2 = V.legal_form(name), V.legal_form(rec["legal_name"])
                    if band == "pass" and f1 and f2 and f1 != f2:
                        flag(
                            "R10",
                            f"legal form differs: declared '{name}' but the GST registry has '{rec['legal_name']}' (private limited, public limited and LLP are different entities)",
                            "legal_name",
                        )
                    if band == "conflict":
                        flag(
                            "R10",
                            f"declared '{name}' vs GST registry '{rec['legal_name']}' (score {sc})",
                            "legal_name",
                            outcome=E,
                        )
                    elif band == "review":
                        flag(
                            "R10", f"declared name differs from GST registry name (score {sc})", "legal_name"
                        )
            except TimeoutError as e:
                outage(e, "gstin", "GST registration")
        if p_ok:
            try:
                pr = reg.pan_lookup(pan)
                if pr is not None:
                    ev("pan", registry="operative" if pr.get("pan_operative", True) else "INOPERATIVE")
                    if pr.get("pan_operative") is False:
                        flag("R17", "PAN is not operative", "pan")
                    if (
                        sub.get("no_gst")
                        and not gstin
                        and pr.get("gstin")
                        and pr.get("gst_status") == "Active"
                    ):
                        flag(
                            "R37",
                            f"declared as not GST-registered, but this PAN has an active GST registration ({pr['gstin']})",
                            "gstin",
                        )
            except TimeoutError as e:
                outage(e, "pan", "PAN status")
        if sub.get("udyam") and not any(f["rule"] == "R18" for f in F):
            try:
                if reg.udyam_lookup(sub["udyam"].strip().upper()) is None:
                    flag("R18", "Udyam number not found", "udyam")
            except TimeoutError as e:
                outage(e, "udyam", "Udyam")
        if cin:
            try:
                m = reg.mca_lookup(cin)
                if m is not None:
                    ev("cin", registry=m.get("status"))
                    if str(m.get("status", "")).lower() != "active":
                        flag("R22", f"MCA status: {m.get('status')}", "cin")
                    if m.get("inc_date") and V.cin_year_matches_incorporation(cin, m["inc_date"]) is False:
                        flag("R23", "CIN year differs from MCA incorporation date", "cin")
            except TimeoutError as e:
                outage(e, "cin", "company status")

    # ---- cross-checks: claims vs evidence -----------------------------------------------------------------
    stage("crosscheck", "Comparing declared details with documents")
    for doc, key, claim, rule in (
        ("gst_cert", "gstin", gstin, "R03"),
        ("pan_card", "pan", pan, "R04"),
        ("cheque", "ifsc", ifsc, "R08"),
    ):
        d = docs.get(doc) or {}
        v = d.get(key)
        cands = d.get("candidates") or []
        if doc == "gst_cert" and len(cands) > 1:
            ev("gstin", document=", ".join(cands))
            if claim and claim not in cands and not (key == "gstin" and not g_ok):
                flag("R03", f"document shows GSTINs {', '.join(cands)}; none is the declared {claim}", key)
            continue
        if (
            v and d.get("how") == "format-only"
        ):  # read but not in the RBI list: low confidence, informational only (never blames the vendor for an OCR guess)
            ev(key, document=f"{v} (low confidence)")
            continue
        if v:
            ev(key, document=v)
        if doc == "gst_cert" and d.get("doctype") == "invoice-like" and v and claim and v.upper() != claim:
            ev(key, document=f"{v} (one GSTIN of several on an invoice; not conclusive)")
            continue  # invoices carry supplier AND buyer GSTINs
        if v and claim and v.upper() != claim and not (key == "gstin" and not g_ok):
            flag(rule, f"{doc} shows {key.upper()} {v} but the form says {claim}", key)
    ch = docs.get("cheque") or {}
    if (
        ch
        and not ch.get("abstained")
        and ifsc
        and re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc)
        and V.ifsc_exists(ifsc)
        and not any(f["rule"] in ("R08", "R09") for f in F)
    ):
        import cheque_verify as CV

        cvv = CV.verify(
            ifsc,
            None,
            ocr_text=ch.get("text"),
            ifsc_read=ch.get("ifsc"),
            ifsc_how=ch.get("how") or "none",
            micr=ch.get("micr") or [],
        )
        A.add("crosscheck", "cheque_verify", verdict=cvv["verdict"], signals=cvv["signals"])
        ev(
            "ifsc",
            cheque_check=f"{cvv['verdict']} ({', '.join(k + ':' + v for k, v in cvv['signals'].items()) or 'no signal read'})",
        )
        if cvv["verdict"] in ("contradicted", "conflicting"):
            flag(
                "R31",
                "the cancelled cheque does not match the declared bank/branch"
                + (": " + "; ".join(cvv["notes"]) if cvv["notes"] else ""),
                "ifsc",
                outcome=P if cvv["verdict"] == "contradicted" else E,
            )
    if ch and not ch.get("abstained") and account:
        import cheque_verify as CV

        am = CV.account_match(account, ch.get("account_candidates") or [])
        ev(
            "account",
            cheque={
                "match": "account number on the cheque agrees",
                "differs": "account number on the cheque differs",
                "unread": "account number not legible on the cheque",
            }[am],
        )
        if am == "differs":
            flag("R32", "account number on the cancelled cheque differs from the declared account", "account")

    def _prints_a_name(txt):
        """Most cheque leaves are blank apart from the bank; judge the holder name only if some entity-like name is actually printed."""
        boiler = set(
            "PAY OR BEARER ORDER RUPEES CHEQUE CANCELLED CANCELED BANK LIMITED LTD BRANCH IFSC MICR ACCOUNT DATE SIGNATURE AUTHORISED AUTHORIZED SIGNATORY VALID MONTHS THREE ONLY NOT NEGOTIABLE ROAD STREET NAGAR MARG COLONY PHONE EMAIL WEBSITE CODE SAVINGS CURRENT SB CA RS FOR AND THE".split()
        )
        import cheque_verify as CV

        bw = (
            {w.upper() for b in CV.bank_words(ifsc[:4]) for w in re.findall(r"[A-Za-z]{3,}", b)}
            if ifsc
            else set()
        )
        words = [w for w in re.findall(r"[A-Z]{4,}", txt.upper()) if w not in boiler and w not in bw]
        return len(words) >= 2

    if (
        ch.get("text")
        and name
        and len(ch["text"]) > 60
        and not ch.get("abstained")
        and _prints_a_name(ch["text"])
    ):
        sc, why = V.name_in_text(name, ch["text"])
        ev("legal_name", cheque=f"declared name found on cheque: {sc}% of its words")
        if sc < 50:
            flag(
                "R10",
                f"legal name not found on the cheque ({sc}% of its words); the account may belong to someone else",
                "account_holder",
                outcome=E,
            )
        elif sc < 85:
            flag("R10", f"only part of the legal name appears on the cheque ({sc}%)", "account_holder")
    ud = docs.get("udyam_cert") or {}
    if ud and not ud.get("abstained") and ud.get("udyam"):
        ev(
            "udyam",
            document=ud["udyam"] + (f" ({ud['enterprise_class']})" if ud.get("enterprise_class") else ""),
        )
        claimed_u = (sub.get("udyam") or "").strip().upper()
        if claimed_u and claimed_u != ud["udyam"]:
            flag("R33", f"Udyam certificate shows {ud['udyam']} but the form says {claimed_u}", "udyam")
    gd = docs.get("gst_cert") or {}
    if gd.get("composition"):
        ev("gstin", document="composition-scheme registration")
    for doc in ("gst_cert", "pan_card", "udyam_cert"):
        dn = (docs.get(doc) or {}).get("name")
        if dn and name:
            sc = V.name_score(name, dn)
            tn = (docs.get(doc) or {}).get("trade_name")
            if tn:
                sc = max(sc, V.name_score(name, tn))  # a vendor may legitimately use its trade name
            band = V.name_band(sc)
            ev("legal_name", **{doc: dn})
            if band == "conflict":
                flag("R10", f"{doc} name '{dn}' vs form '{name}'", "legal_name", outcome=E)
            elif band == "review":
                flag("R10", f"{doc} name '{dn}' differs from form", "legal_name")

    # ---- screening ----------------------------------------------------------------------------------------------
    stage("screening", "Screening sanctions, duplicates and weak signals")
    try:
        hits = reg.sanctions_hits(name) if name else []
        ev("legal_name", sanctions=("possible match: " + hits[0]["name"]) if hits else "no sanctions match")
        if hits:
            flag(
                "R19", f"name matches {len(hits)} watch-list record(s), e.g. {hits[0]['name']}", "legal_name"
            )
    except TimeoutError as e:
        outage(e, "legal_name", "sanctions screening")
    nn = V.normalise_name(name)
    for ex in existing or []:
        if ex.get("fam"):  # an earlier Approved run of this same vendor: only a changed bank account matters
            if (
                ex.get("status") == "Approved"
                and account
                and ex.get("account")
                and (ex.get("account") != account or ex.get("ifsc") != ifsc)
            ):
                sub["bank_change"] = True
                flag(
                    "R27",
                    "this vendor was already approved with a different bank account: verify by call-back to the number on file",
                    "account",
                )
            continue
        same_id = (gstin and ex.get("gstin") == gstin) or (pan and ex.get("pan") == pan)
        if account and ex.get("account") == account and ex.get("ifsc") == ifsc and not same_id:
            flag("R11", f"bank account already registered to vendor '{ex.get('id')}'", "account")
            break
        if (
            same_id
            and ex.get("status") == "Approved"
            and account
            and ex.get("account")
            and ex.get("account") != account
        ):
            sub["bank_change"] = True  # inferred: an approved vendor now presents a different account
            flag(
                "R27",
                f"existing approved vendor '{ex.get('id')}' now declares a different bank account: verify by call-back to the number on file",
                "account",
            )
            break
        if same_id:
            flag("R12", f"already onboarded as '{ex.get('id')}' (same tax ID)", "gstin")
            break
        if nn and V.name_score(nn, V.normalise_name(ex.get("id") or "")) >= 95:
            flag(
                "R12",
                f"name is almost identical to existing vendor '{ex.get('id')}' with a different tax ID (look-alike)",
                "legal_name",
            )
            break
    addr = (sub.get("address") or "").strip().lower()
    if (
        addr
        and sum(
            1
            for ex in (existing or [])
            if (ex.get("address") or "").strip().lower() == addr and ex.get("pan") != pan
        )
        >= 5
    ):
        flag("R24", "address shared with 5+ unrelated vendors", "address")
    if sub.get("bank_change"):
        flag("R27", "existing vendor changed bank details: verify by call-back to a known number", "account")

    # ---- paid check last: only when every cheaper check is clean (cost ordering) -------------------------------
    clean_so_far = not any(f["outcome"] in (P, E, R) for f in F)
    if country == "IN" and ifsc and account:
        if clean_so_far:
            try:
                ben = reg.bank_verify(ifsc, account)
                if ben is None:
                    flag("R20", "bank could not confirm this account number for this IFSC", "account")
                else:
                    sc = _bank_name_score(name, ben)
                    pc = docs.get("pan_card") or {}
                    if (
                        sc < 85 and pc.get("name") and not pc.get("abstained") and pan and pan[3] in "PH"
                    ):  # a proprietor's account is often in the owner's own name
                        sc = max(sc, V.name_score(pc["name"], ben))
                    ev("account", bank=f"beneficiary '{ben}' (match {sc})")
                    if sc < 60:
                        flag(
                            "R20",
                            f"bank says account holder is '{ben}' - differs from legal name",
                            "account",
                            outcome=E,
                        )
                    elif sc < 85:
                        flag("R20", f"bank beneficiary '{ben}' only partly matches legal name", "account")
                A.add("registry", "paid_check", service="bank_verify")
            except TimeoutError as e:
                outage(e, "account", "bank account")
        else:
            A.add(
                "registry",
                "paid_check_skipped",
                reason="earlier checks already failed; saved one paid verification",
            )

    # ---- decision -------------------------------------------------------------------------------------------------
    tier = risk_tier(sub)
    stage("decision", f"Risk tier {tier}; deciding")
    strong = [f for f in F if f["outcome"] != F_]
    top = max((f["outcome"] for f in strong), key=lambda o: PRECEDENCE[o], default=None)
    weak = [f for f in F if f["outcome"] == F_]
    if top is None and len(weak) >= 2:
        top = E
        A.add("decision", "weak_flags_accumulated", rules=[f["rule"] for f in weak])
    status = {None: "Approved", P: "Pending", E: "Escalated", R: "Rejected"}[top]
    if status == "Approved" and tier == "High":
        flag("R28", "High-risk tier: human sign-off required even though all checks passed")
        status = "Escalated"
    ALIAS = {"gst_cert": "gstin", "cheque": "ifsc", "pan_card": "pan", "account_holder": "legal_name"}
    if g_ok and sub.get("state"):
        ev("state", registry=f"GSTIN state code {gstin[:2]} = {V.GST2ISO.get(gstin[:2], '?')}")
    if any(a["event"] == "paid_check_skipped" for a in A.entries):
        ev("account", bank="not run (earlier checks failed; paid check skipped)")
    for f in F:  # keep matrix verdict per field
        m = M.setdefault(ALIAS.get(f["field"], f["field"]) or "-", {})
        m["verdict"] = max([m.get("verdict")] + [f["outcome"]], key=lambda o: PRECEDENCE.get(o, 0))
    A.add("decision", status, tier=tier, rules=[f["rule"] for f in F])
    prof = build_profile(sub, F, M, tier, status)

    def _summary():
        strong_ = [f for f in F if f["outcome"] in (P, E, R)]
        why = "; ".join(
            dict.fromkeys(
                (
                    f["detail"]
                    if f["rule"] != "R02" or "did you mean" not in f["detail"]
                    else "the GSTIN entered looks mistyped"
                )[:150].rstrip(". ")
                for f in strong_[:2]
            )
        )
        return {
            "Approved": "Approved: the details the vendor typed agree with its documents and the registries, nothing needed a person.",
            "Pending": "Held for the vendor to fix: " + why + ".",
            "Escalated": "Sent to a person to decide: " + why + ".",
            "Rejected": "Rejected: " + why + ".",
        }.get(status, status) + (
            ""
            if country == "IN"
            else " Only the identifier formats were checked for this country (no registry or documents), so a person should verify the rest."
        )

    return dict(
        status=status,
        tier=tier,
        summary=_summary(),
        findings=F,
        matrix=M,
        profile=prof,
        work_secs=round(time.time() - _T0, 2),
        vendor_message=_message(status, F),
        audit=A.entries,
        audit_ok=Audit.verify(A.entries),
        paid_checks=getattr(reg, "paid_calls", 0),
        claimed=dict(name=name, pan=_mask(pan), gstin=gstin),
    )


def _message(status, F):
    if status == "Approved":
        return "Thank you - your details are verified and your vendor profile is active."
    if status == "Rejected":
        return (
            "We are unable to onboard this vendor at this time. "
            + " ".join(f["detail"] for f in F if f["outcome"] == R)
            + " If you believe this is a mistake, or your registration status has changed, please contact the procurement team with your current GST certificate."
        )
    seen, lines = set(), []
    for f in F:
        if f["outcome"] == P and f["fix"] and f["rule"] not in seen:
            seen.add(f["rule"])
            if f["rule"] == "R25":
                lines.append(f"- {f['detail']}")
            elif f["rule"] in ("R02", "R03") and "did you mean" in f["detail"]:
                lines.append(
                    "- The GSTIN you entered is not valid, it looks like a typo. Did you mean "
                    + f["detail"].split("did you mean ")[1].rstrip("?")
                    + "?"
                )
            else:
                lines.append(
                    f"- {f['fix']}"
                    + (f" ({f['detail']})" if f["rule"] in ("R02", "R03", "R08", "R09", "R31", "R32") else "")
                )
    if (
        status == "Escalated"
    ):  # never tip the vendor off about screening/duplicate reasons, but do surface what they can fix
        base = "Thank you. Your submission has been passed to our team for a review. You do not need to do anything unless we contact you."
        return base + (
            ("\n\nOptional: correcting these now will help the review go faster:\n" + "\n".join(lines))
            if lines
            else ""
        )
    if seen == {"R26"}:
        return "Thank you. " + RULES["R26"][2]
    return "Almost there. Please fix the following and resubmit:\n" + "\n".join(lines)
