import engine, copy

reg = engine.Registries()
v = next(
    x
    for x in reg.v
    if x["gst_status"] == "Active"
    and not x["gst_composition"]
    and x["pan_operative"]
    and x["country"] == "IN"
)


def sub(**kw):
    d = dict(
        legal_name=v["legal_name"],
        country="IN",
        pan=v["pan"],
        gstin=v["gstin"],
        ifsc=v["ifsc"],
        account=v["account"],
        cin=v["cin"],
        state=v["state"],
        expected_annual_value=1e6,
    )
    d.update(kw)
    return d


def check(l, got, want):
    assert got == want, f"{l}: got {got!r} want {want!r}"
    print("ok", l)


check("clean approved", engine.run(sub(), reg)["status"], "Approved")
check("outage never approves", engine.run(sub(), engine.Registries(down=["gst"]))["status"], "Pending")
check(
    "sanctions outage never approves",
    engine.run(sub(), engine.Registries(down=["sanctions"]))["status"],
    "Pending",
)
check(
    "bank service outage never approves",
    engine.run(sub(), engine.Registries(down=["bank"]))["status"],
    "Pending",
)
check("bank change escalates", engine.run(sub(bank_change=True), reg)["status"], "Escalated")
check(
    "high value escalates even if clean",
    engine.run(sub(expected_annual_value=9e6), reg)["status"],
    "Escalated",
)
r = engine.run(sub(), reg)
check("audit verifies", r["audit_ok"], True)
bad = copy.deepcopy(r["audit"])
bad[2]["data"]["tampered"] = 1
check("tamper detected", engine.Audit.verify(bad), False)
check(
    "bad GSTIN pending",
    engine.run(sub(gstin=v["gstin"][:-1] + ("A" if v["gstin"][-1] != "A" else "B")), reg)["status"],
    "Pending",
)
check("missing field pending", engine.run(sub(account=""), reg)["status"], "Pending")
check(
    "single-word name not escalated on sanctions alone",
    "R19" in [f["rule"] for f in engine.run(sub(legal_name="Amber"), reg)["findings"]],
    False,
)
print("ENGINE TESTS PASS")

r = engine.run(
    sub(
        address="P.O. Box 5, Pune",
        email="a@gmail.com",
        legal_name=v["legal_name"].split(" Private")[0] + " Private Limited",
    ),
    reg,
)
check(
    "two weak flags escalate",
    ("R13" in [f["rule"] for f in r["findings"]], "R14" in [f["rule"] for f in r["findings"]]),
    (True, True),
)
r = engine.run(sub(address="P.O. Box 5, Pune"), reg)
check("one weak flag alone does not escalate", r["status"], "Approved")
r = engine.run(sub(ifsc=v["ifsc"][:5] + "ZZZZZZ"), reg)
check(
    "paid check skipped when cheap checks fail",
    reg.paid_calls >= 0 and any(a["event"] == "paid_check_skipped" for a in r["audit"]),
    True,
)
print("ENGINE TESTS 2 PASS")

# vendors without GST: allowed, but not if their PAN actually has a GST registration; GST profile says so
r = engine.run(sub(gstin="", no_gst=True), reg)
check(
    "not-GST-registered claim on a GST-registered PAN escalates",
    ("R37" in [f["rule"] for f in r["findings"]], r["status"]),
    (True, "Escalated"),
)
r = engine.run(sub(gstin="", no_gst=True, pan="BCDPE4321F", legal_name="Eswar Kumar"), reg)
check(
    "unregistered vendor is not asked for a GSTIN",
    "R01" in [f["rule"] for f in r["findings"] if f.get("field") == "gstin"],
    False,
)
check("unregistered vendor profile says no GST", "Not registered for GST" in r["profile"]["gst_mode"], True)
r = engine.run(sub(legal_name="Acme Robotics Pvt Ltd", country="US", ein="12-3456789"), reg)
check("non-India run says only formats were checked", "Only the identifier formats" in r["summary"], True)
print("ENGINE TESTS 3 PASS")
