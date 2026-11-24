import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Labelled evaluation of the engine. Three sets, dev/held-out split by vendor id (even/odd).
  clean   : vendors whose registry record is genuinely healthy -> must be Approved (false-block rate)
  noise   : benign variations a real vendor produces (case, spacing, M/S, P LTD, trade name) -> must NOT be flagged
  mutated : one injected defect each, with the rule that must fire and the minimum severity expected (recall)
Outputs data/real/eval_engine.json and prints a table."""
import json, random, collections, re, sys
import engine, validators as V

random.seed(7)
reg = engine.Registries()
healthy = [
    x
    for x in reg.v
    if x["gst_status"] == "Active"
    and not x["gst_composition"]
    and x["pan_operative"]
    and V.ifsc_status(x["ifsc"]) == "ok"
    and x["country"] == "IN"
]
SEV = {"F": 0, "P": 1, "E": 2, "R": 3}


def base(x, **kw):
    d = dict(
        legal_name=x["legal_name"],
        country="IN",
        pan=x["pan"],
        gstin=x["gstin"],
        ifsc=x["ifsc"],
        account=x["account"],
        cin=x["cin"],
        state=x["state"],
        expected_annual_value=1_000_000,
        docs=dict(
            gst_cert=dict(gstin=x["gstin"], name=x["legal_name"]),
            cheque=dict(ifsc=x["ifsc"], holder=x["legal_name"]),
        ),
    )
    d.update(kw)
    return d


def flip_char(s, i):
    alt = "B" if s[i] != "B" else "C"
    return s[:i] + alt + s[i + 1 :]


def swap_adjacent(s):
    for _ in range(50):
        i = random.randrange(2, len(s) - 3)
        t = s[:i] + s[i + 1] + s[i] + s[i + 2 :]
        if t != s:
            return t
    return s


def other(x, differ="name"):
    """A genuinely different vendor: name score < 60 (else the pair legitimately sits in the review band) and different IFSC if asked."""
    pool = [
        y
        for y in healthy
        if y["id"] != x["id"]
        and V.name_score(x["legal_name"], y["legal_name"]) < 60
        and (differ != "ifsc" or y["ifsc"] != x["ifsc"])
    ]
    return random.choice(pool)


MUT = {  # name -> (builder, accepted rule(s), minimum outcome)
    "gstin_typo": (lambda x: base(x, gstin=flip_char(x["gstin"], 6)), ("R02", "R03"), "P"),
    "gstin_transposed": (lambda x: base(x, gstin=swap_adjacent(x["gstin"])), ("R02", "R03"), "P"),
    "gstin_wrong_pan": (lambda x: base(x, pan=other(x)["pan"]), ("R05",), "E"),
    "pan_malformed": (lambda x: base(x, pan=x["pan"][:5] + "ABCD"), ("R04",), "P"),
    "ifsc_unknown_branch": (lambda x: base(x, ifsc=x["ifsc"][:5] + "ZZZZZZ"), ("R08",), "P"),
    "ifsc_bad_format": (lambda x: base(x, ifsc=x["ifsc"][:4] + "1" + x["ifsc"][5:]), ("R08",), "P"),
    "bank_differs_from_ifsc": (lambda x: base(x, bank="Some Other Bank"), ("R09",), "P"),
    "cheque_ifsc_differs": (
        lambda x: base(x, docs=dict(cheque=dict(ifsc=other(x, "ifsc")["ifsc"], holder=x["legal_name"]))),
        ("R08",),
        "P",
    ),
    "third_party_account": (
        lambda x: (
            lambda o: base(
                x,
                ifsc=o["ifsc"],
                account=o["account"],
                docs=dict(cheque=dict(ifsc=o["ifsc"], holder=x["legal_name"])),
            )
        )(other(x, "ifsc")),
        ("R20",),
        "E",
    ),
    "account_not_confirmed": (
        lambda x: base(x, account=x["account"][:-1] + ("1" if x["account"][-1] != "1" else "2")),
        ("R20",),
        "P",
    ),
    "gst_cert_other_entity": (
        lambda x: base(x, docs=dict(gst_cert=dict(gstin=x["gstin"], name=other(x)["legal_name"]))),
        ("R10",),
        "E",
    ),
    "name_vs_registry": (lambda x: base(x, legal_name=other(x)["legal_name"]), ("R10",), "E"),
    "cancelled_gstin": (None, ("R16",), "R"),
    "missing_bank": (lambda x: base(x, account=""), ("R01",), "P"),
    "bank_change": (lambda x: base(x, bank_change=True), ("R27",), "E"),
    "sanctioned_name": (None, ("R19",), "E"),
    "cin_malformed": (lambda x: base(x, cin=x["cin"][:15] + "XYZ" + x["cin"][18:]), ("R21",), "P"),
    "udyam_malformed": (lambda x: base(x, udyam="UDYAM-ZZ-1-12"), ("R18",), "P"),
    "state_mismatch": (
        lambda x: base(x, state="Kerala" if x["state"] != "Kerala" else "Assam"),
        ("R07",),
        "P",
    ),
    "po_box_plus_webmail": (
        lambda x: base(x, address="P.O. Box 123, Mumbai", email="owner@gmail.com"),
        ("R14",),
        "E",
    ),
}

NOISE = {
    "upper": lambda n: n.upper(),
    "lower": lambda n: n.lower(),
    "double_space": lambda n: n.replace(" ", "  "),
    "ms_prefix": lambda n: "M/S " + n,
    "p_ltd": lambda n: re.sub(r"Private Limited", "P LTD", n, flags=re.I),
    "pvt": lambda n: re.sub(r"Private Limited", "Pvt. Ltd.", n, flags=re.I),
    "ampersand": lambda n: n.replace(" and ", " & "),
    "trailing_dot": lambda n: n + ".",
}


def split(x):
    return "dev" if int(x["id"][1:]) % 2 == 0 else "held"


def decide(sub, **k):
    return engine.run(sub, reg, **k)


rows = []
for x in healthy:
    r = decide(base(x))
    rows.append(
        dict(
            kind="clean",
            name="clean",
            split=split(x),
            ok=r["status"] == "Approved",
            got=r["status"],
            rules=[f["rule"] for f in r["findings"]],
        )
    )
    for nm, fn in NOISE.items():
        sub = base(x, legal_name=fn(x["legal_name"]))
        r = decide(sub)
        rows.append(
            dict(
                kind="noise",
                name=nm,
                split=split(x),
                ok=r["status"] == "Approved",
                got=r["status"],
                rules=[f["rule"] for f in r["findings"]],
            )
        )
    for nm, (fn, rules_, minsev) in MUT.items():
        if fn is None:
            continue
        if nm == "cin_malformed" and not x.get("cin"):
            continue
        if nm == "po_box_plus_webmail" and "limited" not in x["legal_name"].lower():
            continue  # webmail flag applies to companies
        sub = fn(x)
        r = decide(sub)
        fired = [f for f in r["findings"] if f["rule"] in rules_]
        sev_ok = {
            "P": ("Pending", "Escalated", "Rejected"),
            "E": ("Escalated", "Rejected"),
            "R": ("Rejected",),
        }[minsev]
        rows.append(
            dict(
                kind="mutated",
                name=nm,
                split=split(x),
                ok=bool(fired) and r["status"] in sev_ok,
                got=r["status"],
                rules=[f["rule"] for f in r["findings"]],
                want="/".join(rules_),
            )
        )

# registry-state mutations use real unhealthy records the generator planted (cancelled / suspended)
for x in reg.v:
    if x["gst_status"] in ("Cancelled", "Suspended"):
        r = decide(base(x))
        want_status = "Rejected" if x["gst_status"] == "Cancelled" else "Pending"
        rows.append(
            dict(
                kind="mutated",
                name=x["gst_status"].lower() + "_gstin",
                split=split(x),
                ok="R16" in [f["rule"] for f in r["findings"]] and r["status"] == want_status,
                got=r["status"],
                rules=[f["rule"] for f in r["findings"]],
                want="R16",
            )
        )
# sanctions: take real SDN entity names, onboard them under a fabricated valid-looking vendor record
sdn = [s for s in reg.sanctions if s.get("type") in ("-0-", None, "entity", "Entity")][:400]
for i, s in enumerate(random.sample(sdn, min(60, len(sdn)))):
    x = random.choice(healthy)
    r = decide(base(x, legal_name=s["name"]))
    rows.append(
        dict(
            kind="mutated",
            name="sanctioned_name",
            split="dev" if i % 2 == 0 else "held",
            ok="R19" in [f["rule"] for f in r["findings"]],
            got=r["status"],
            rules=[f["rule"] for f in r["findings"]],
            want="R19",
        )
    )

# ---- report ----
out = {}


def rate(sel):
    return (sum(r["ok"] for r in sel), len(sel))


print(f"{'set':8s}{'case':24s}{'dev':>10s}{'held-out':>12s}")
for kind in ("clean", "noise", "mutated"):
    names = sorted({r["name"] for r in rows if r["kind"] == kind})
    for nm in names:
        d = rate([r for r in rows if r["kind"] == kind and r["name"] == nm and r["split"] == "dev"])
        h = rate([r for r in rows if r["kind"] == kind and r["name"] == nm and r["split"] == "held"])
        out[f"{kind}/{nm}"] = dict(dev=d, held=h)
        print(f"{kind:8s}{nm:24s}{d[0]:>5d}/{d[1]:<4d}{h[0]:>7d}/{h[1]:<4d}")
cl = rate([r for r in rows if r["kind"] in ("clean", "noise")])
mu = rate([r for r in rows if r["kind"] == "mutated"])
print(f"\nfalse-block rate on clean+benign-noise: {100*(1-cl[0]/cl[1]):.1f}%  ({cl[1]-cl[0]}/{cl[1]})")
print(f"defect recall (right rule fired at right severity): {100*mu[0]/mu[1]:.1f}%  ({mu[0]}/{mu[1]})")
fails = [r for r in rows if not r["ok"]]
print("\nfailure sample:")
[print(" ", r["kind"], r["name"], r["got"], r["rules"], r.get("want", "")) for r in fails[:25]]
out["summary"] = dict(false_block=cl, recall=mu)
out["failures"] = fails[:200]
json.dump(out, open("data/real/eval_engine.json", "w"), indent=1)
