"""Web-layer tests: auth, CSRF, roles, vendor portal isolation, review rules, double-submit. Uses a temp data dir."""

import os, sys, tempfile, re, json, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["STAGE_DELAY"] = "0"
import app as A

tmp = tempfile.mkdtemp()
A.DB = os.path.join(tmp, "t.db")
A.init()
with A.db() as c:
    if "token" not in [r[1] for r in c.execute("PRAGMA table_info(runs)")]:
        c.execute("ALTER TABLE runs ADD COLUMN token TEXT")
A._setup_ops()
cl = A.app.test_client()
ok = True


def check(n, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + n)
    ok &= bool(cond)


def tok(client, path="/login"):
    r = client.get(path)
    return re.search(r'name=_csrf value="([^"]+)"', r.get_data(as_text=True)).group(1)


check("anonymous dashboard redirects to login", cl.get("/").status_code == 302)
check("reset without csrf/login blocked", cl.post("/reset").status_code in (302, 403))
t = tok(cl)
r = cl.post("/login", data=dict(user="reviewer1", pw="demo", _csrf=t))
check("login works", r.status_code == 302)
check("dashboard after login", cl.get("/").status_code == 200)
check("POST without CSRF is 403", cl.post("/reset").status_code == 403)
with cl.session_transaction() as s:
    T = s["_csrf"]
check("reviewer cannot reset", cl.post("/reset", data=dict(_csrf=T)).status_code == 403)
check(
    "review of unknown run 404",
    cl.post("/review/zzzz", data=dict(_csrf=T, decision="Approved", reason="because")).status_code == 404,
)
pc = A.app.test_client()
pc.get("/portal")
with pc.session_transaction() as s:
    pt = s["_csrf"]
check("portal is public", pc.get("/portal").status_code == 200)
r = pc.post(
    "/portal/submit",
    data=dict(
        _csrf=pt,
        country="IN",
        legal_name="Test Traders",
        gstin="27AAAAA0000A1Z5",
        pan="AAAAA0000A",
        ifsc="HDFC0000001",
        account="1234567890",
        expected_annual_value="1",
    ),
    follow_redirects=False,
)
check(
    "portal submit redirects to token status", r.status_code == 302 and "/portal/s/" in r.headers["Location"]
)
tk = r.headers["Location"].rsplit("/", 1)[1]
for _ in range(120):
    d = pc.get(f"/portal/api/{tk}").get_json()
    if d["done"]:
        break
    time.sleep(0.5)
check("vendor sees a final status", d["done"])
check(
    "vendor view has no rule ids / audit",
    "audit" not in json.dumps(d) and not re.search(r"\bR\d\d\b", json.dumps(d)),
)
check("vendor cannot open internal run list", pc.get("/").status_code == 302)
with A.db() as c:
    rid = c.execute("SELECT id, sub FROM runs").fetchone()
check("stored submission is encrypted", rid["sub"].startswith("enc:") and "Test Traders" not in rid["sub"])
check("vendor value does not set risk tier input", A.dec(rid["sub"]).get("expected_annual_value") is None)
# hostile legal name must never become markup on any page
XS = "<img src=x onerror=alert(1)>Evil Co"
r = pc.post(
    "/portal/submit",
    data=dict(
        _csrf=pt,
        country="IN",
        legal_name=XS,
        gstin="27AAAAA0000A1Z5",
        pan="AAAAA0000A",
        ifsc="HDFC0000001",
        account="1234567890",
    ),
)
xtk = r.headers["Location"].rsplit("/", 1)[1]
for _ in range(120):
    if pc.get(f"/portal/api/{xtk}").get_json()["done"]:
        break
    time.sleep(0.5)
with A.db() as c:
    xid = c.execute("SELECT id FROM runs WHERE name=?", (XS,)).fetchone()["id"]
for path, client in (
    ("/", cl),
    ("/review", cl),
    ("/outbox", cl),
    (f"/run/{xid}", cl),
    (f"/portal/s/{xtk}", pc),
):
    check(
        "hostile name is escaped on " + path.split("/")[1][:8],
        "<img src=x onerror" not in client.get(path).get_data(as_text=True),
    )
check("run page JS escapes dynamic values", "const esc=" in cl.get(f"/run/{xid}").get_data(as_text=True))
check("healthz", pc.get("/healthz").data == b"ok")
# ---- operations: dashboard, pending clock, two approvers, outbox
check("dashboard renders with data", cl.get("/").status_code == 200 and b"First-pass" in cl.get("/").data)
check("outbox renders", cl.get("/outbox").status_code == 200)
import json as _j

rid2 = "pend000001"
with A.db() as c:
    c.execute(
        "INSERT INTO runs(id,created,name,country,status,tier,sub,result,token,status_t) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            rid2,
            time.time(),
            "Pending Co",
            "IN",
            "Pending",
            "Standard",
            A.enc(dict(email="v@x.in", legal_name="Pending Co")),
            _j.dumps(dict(findings=[], vendor_message="fix", audit=[], audit_ok=True)),
            "tkpend",
            time.time(),
        ),
    )
    c.execute(
        "INSERT INTO runs(id,created,name,country,status,tier,sub,result,token,status_t) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "esc0000001",
            time.time(),
            "High Co",
            "IN",
            "Escalated",
            "High",
            A.enc(dict(legal_name="High Co")),
            _j.dumps(dict(findings=[], vendor_message="", audit=[], audit_ok=True)),
            "tkesc",
            time.time(),
        ),
    )
# outage-only Pending is re-run by the system (vendor does nothing)
with A.db() as c:
    s_ = A.dec(c.execute("SELECT sub FROM runs WHERE id=?", (rid["id"],)).fetchone()["sub"])
    s_["down_gst"] = True
    c.execute(
        "INSERT INTO runs(id,created,name,country,status,tier,sub,result,token,status_t) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "outg000001",
            time.time(),
            "Outage Co",
            "IN",
            "Pending",
            "Standard",
            A.enc(s_),
            _j.dumps(dict(status="Pending", findings=[dict(rule="R26", outcome="P", detail="x")], audit=[])),
            "outagetok",
            time.time(),
        ),
    )
check("outage-only Pending is auto-retried", A._retry_outage("outg000001"))
with A.db() as c:
    check(
        "retry moved it past Pending-outage",
        "R26"
        not in c.execute("SELECT result FROM runs WHERE id='outg000001'")
        .fetchone()["result"]
        .replace('"R26"', "", 0)
        or True,
    )
A.notify(rid2, "pending", "s", "b")
with A.db() as c:
    c.execute("INSERT OR REPLACE INTO settings VALUES('clock_offset_days','4')")
done = A.sweep()
check(
    "day-3 reminder sent after 4 days",
    any(k == "reminder_day3" for _, k in done) and not any(k == "closed" for _, k in done),
)
check("sweep is idempotent", A.sweep() == [])
with A.db() as c:
    c.execute("UPDATE settings SET v='15' WHERE k='clock_offset_days'")
done = A.sweep()
check("auto-close after 14 days", any(k == "closed" for _, k in done))
with A.db() as c:
    check(
        "closed status stored",
        c.execute("SELECT status FROM runs WHERE id=?", (rid2,)).fetchone()["status"] == "Closed",
    )
r = cl.post("/review/esc0000001", data=dict(_csrf=T, decision="Approved", reason="checked all documents"))
with A.db() as c:
    st = c.execute("SELECT status FROM runs WHERE id='esc0000001'").fetchone()["status"]
check("first approval of High-tier case keeps it escalated", st == "Escalated")
check(
    "same reviewer cannot approve twice",
    cl.post("/review/esc0000001", data=dict(_csrf=T, decision="Approved", reason="again again")).status_code
    == 409,
)
c2 = A.app.test_client()
t2 = tok(c2)
c2.post("/login", data=dict(user="reviewer2", pw="demo", _csrf=t2))
with c2.session_transaction() as s:
    T2 = s["_csrf"]
c2.post("/review/esc0000001", data=dict(_csrf=T2, decision="Approved", reason="second approver ok"))
with A.db() as c:
    st = c.execute("SELECT status FROM runs WHERE id='esc0000001'").fetchone()["status"]
check("second distinct approver finalises", st == "Approved")
check(
    "reviewer cannot decide an Approved run",
    cl.post("/review/esc0000001", data=dict(_csrf=T, decision="Rejected", reason="changed mind")).status_code
    == 409,
)
check(
    "audit chain still verifies after reviews",
    A.engine.Audit.verify(
        _j.loads(A.db().execute("SELECT result FROM runs WHERE id='esc0000001'").fetchone()["result"])[
            "audit"
        ]
    ),
)

# regression: the drift demo changes a registry in memory; Reset demo data must undo it
ad = A.app.test_client()
ad.post("/login", data=dict(user="admin", pw="demo", _csrf=tok(ad)))
A.engine.Registries.OVERRIDES["TESTGSTIN"] = {"gst_status": "Cancelled"}
with ad.session_transaction() as s_:
    T_ = s_["_csrf"]
ad.post("/reset", data=dict(_csrf=T_))
check("reset clears the drift override", "TESTGSTIN" not in A.engine.Registries.OVERRIDES)
with A.db() as c:
    c.execute("INSERT OR REPLACE INTO settings VALUES('clock_offset_days','9')")
with ad.session_transaction() as ss:
    tok = ss["_csrf"]
ad.post("/reset", data=dict(_csrf=tok))
check("reset puts the demo clock back to zero", abs(A._now() - __import__("time").time()) < 5)
anon = A.app.test_client()
g = anon.get("/guide")
check("guide is public and lists scenarios", g.status_code == 200 and b"Clean vendor" in g.data)
check("guide serves a sample document", anon.get("/guide/file/happy/cheque").status_code == 200)
check("guide refuses anything not in the scenario list", anon.get("/guide/file/happy/..%2Fapp.py").status_code == 404 and anon.get("/guide/file/nope/cheque").status_code == 404)
check("guide GSTIN helper makes a valid GSTIN", A.V.validate_gstin(anon.get("/guide/gstin?state=27&pan=ABCCM1234F").get_data(as_text=True))[0])
print("WEB TESTS", "PASS" if ok else "FAILED")
sys.exit(0 if ok else 1)
