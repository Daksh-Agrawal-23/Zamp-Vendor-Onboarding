"""Vendor onboarding web app: intake form, live run view, dashboard, reviewer queue, evaluation page."""

import collections, json, os, sqlite3, threading, time, uuid, glob
from markupsafe import escape
from flask import (
    g,
    Flask,
    request,
    redirect,
    url_for,
    jsonify,
    render_template,
    render_template_string,
    send_from_directory,
    abort,
)
import engine, docread, validators as V, security
from security import enc, dec

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "app.db")
UP = os.path.join(HERE, "data", "uploads")
os.makedirs(UP, exist_ok=True)
app = Flask(__name__)
# Behind a hosting proxy (Hugging Face, Render, Fly) the real client address and scheme arrive in X-Forwarded-* headers.
# Without this, the portal rate limit would treat every visitor as one address. TRUST_PROXY=0 turns it off.
if os.environ.get("TRUST_PROXY", "1") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
MAX_FILE = 12 * 1024 * 1024
security.init_app(app)
STAGE_DELAY = float(
    os.environ.get("STAGE_DELAY", "1.4")
)  # slows stages slightly so the live view is watchable
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg"}
LABEL = {
    "intake": "Intake",
    "documents": "Read documents",
    "format": "Validate identifiers",
    "registry": "Registry lookups",
    "crosscheck": "Cross-check claims vs evidence",
    "screening": "Sanctions & duplicates",
    "decision": "Decision",
}


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.executescript(
            """CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created REAL, name TEXT, country TEXT, status TEXT, tier TEXT,
            sub TEXT, result TEXT, resubmit_of TEXT);
            CREATE TABLE IF NOT EXISTS events(run_id TEXT, seq INTEGER, t REAL, stage TEXT, msg TEXT);
            CREATE TABLE IF NOT EXISTS reviews(run_id TEXT, t REAL, reviewer TEXT, decision TEXT, reason TEXT);"""
        )
        if "token" not in [r[1] for r in c.execute("PRAGMA table_info(runs)")]:
            c.execute("ALTER TABLE runs ADD COLUMN token TEXT")


init()


def _registries(sub):
    down = [d for d in ("gst", "pan", "mca", "sanctions", "bank", "udyam") if sub.get(f"down_{d}")]
    reg = engine.Registries(down=down)
    if sub.get(
        "demo_registry"
    ):  # demo only: pretend the registries hold this vendor exactly as declared, so a vendor invented live can be approved
        rec = dict(
            id="LIVE",
            legal_name=sub.get("legal_name", ""),
            trade_name=sub.get("legal_name", ""),
            country="IN",
            entity_type="Company",
            pan=sub.get("pan"),
            gstin=sub.get("gstin"),
            gst_status="Active",
            gst_composition=False,
            pan_operative=True,
            state=sub.get("state"),
            cin=sub.get("cin") or None,
            udyam=sub.get("udyam") or None,
            bank=sub.get("bank"),
            ifsc=sub.get("ifsc"),
            account=sub.get("account"),
            address=sub.get("address"),
        )
        reg.by_gstin[rec["gstin"]] = rec
        reg.by_pan[rec["pan"]] = rec
        reg.by_acct[(rec["ifsc"], rec["account"])] = rec
        if rec["udyam"]:
            reg.by_udyam[rec["udyam"]] = rec
    return reg


def _root(c, rid):
    seen = set()
    while rid and rid not in seen:
        seen.add(rid)
        r = c.execute("SELECT resubmit_of FROM runs WHERE id=?", (rid,)).fetchone()
        if not r or not r["resubmit_of"]:
            return rid
        rid = r["resubmit_of"]
    return rid


def _family(c, rid):
    """All runs in one resubmission chain (a vendor correcting its own submission is not a duplicate of itself)."""
    root = _root(c, rid)
    return {r["id"] for r in c.execute("SELECT id FROM runs") if _root(c, r["id"]) == root}


SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("WORKERS", "2"))
)  # at most N runs read documents/OCR at once; the rest queue
RUN_TIMEOUT = int(os.environ.get("RUN_TIMEOUT", "240"))


def process(run_id):
    """Queue-aware wrapper with a watchdog: a stuck run is routed to a person instead of hanging forever."""
    done = threading.Event()

    def watchdog():
        if not done.wait(RUN_TIMEOUT):
            with db() as c:
                c.execute(
                    "UPDATE runs SET status='Escalated', result=? WHERE id=? AND status='Running'",
                    (
                        json.dumps(
                            dict(
                                status="Escalated",
                                findings=[],
                                vendor_message="This is taking longer than expected; a person will pick it up.",
                                audit=[],
                                audit_ok=True,
                            )
                        ),
                        run_id,
                    ),
                )

    threading.Thread(target=watchdog, daemon=True).start()
    with SLOTS:
        try:
            _process(run_id)
        finally:
            done.set()


def _process(run_id):
    with db() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    sub = dec(row["sub"])
    seq = [0]

    def emit(stage, msg):
        seq[0] += 1
        with db() as c:
            c.execute("INSERT INTO events VALUES(?,?,?,?,?)", (run_id, seq[0], time.time(), stage, msg))
        if stage != "finding":
            time.sleep(STAGE_DELAY)

    try:
        # real document reading happens inside the "documents" stage so the viewer sees it
        emit("documents", "Reading uploaded documents (quality check, OCR)")
        docs = {}
        for kind, path in (sub.get("files") or {}).items():
            d = docread.read_document(kind, path, tmp=UP, expect=(sub.get("gstin") or "").strip().upper() or None)
            docs[kind] = d
            q = (d.get("quality") or {}).get("level", "n/a")
            nice = {
                "gst_cert": "GST certificate",
                "cheque": "Cancelled cheque",
                "pan_card": "PAN card",
                "udyam_cert": "Udyam certificate",
            }.get(kind, kind)
            vals = [
                f"{lbl} {d[k]}"
                for k, lbl in (("gstin", "GSTIN"), ("ifsc", "IFSC"), ("pan", "PAN"))
                if d.get(k)
            ]
            qtxt = {
                "good": "clear",
                "ok": "clear",
                "warn": "readable",
                "poor": "poor quality",
                "bad": "too poor to read",
            }.get(q, q)
            emit(
                "finding",
                f"{nice} ({qtxt} scan): "
                + (
                    "read " + ", ".join(vals)
                    if vals
                    else "nothing could be read with confidence, so it is not relied on"
                ),
            )
        sub["docs"] = {k: v for k, v in docs.items()}
        sub["docs_required"] = not sub.get("demo_registry")
        with db() as c:
            c.execute("UPDATE runs SET sub=? WHERE id=?", (enc(sub), run_id))
            fam = _family(c, run_id)
            rows_ = [
                r
                for r in c.execute(
                    "SELECT id, sub, status FROM runs WHERE status IN ('Approved','Pending','Escalated')"
                )
                if r["sub"]
            ]
            existing = [dict(dec(r["sub"]), status=r["status"]) for r in rows_ if r["id"] not in fam] + [
                dict(dec(r["sub"]), status=r["status"], fam=True)
                for r in rows_
                if r["id"] in fam and r["id"] != run_id
            ]
        res = engine.run(
            sub,
            _registries(sub),
            emit=emit,
            existing=[
                dict(
                    id=e.get("legal_name"),
                    gstin=e.get("gstin"),
                    pan=e.get("pan"),
                    status=e.get("status"),
                    account=e.get("account"),
                    ifsc=e.get("ifsc"),
                    address=e.get("address"),
                    fam=e.get("fam"),
                )
                for e in existing
            ],
        )
        with db() as c:
            c.execute(
                "UPDATE runs SET status=?, tier=?, result=? WHERE id=? AND status='Running'",
                (res["status"], res["tier"], json.dumps(res, default=str), run_id),
            )
        if res.get("audit"):
            security.anchor(run_id, res["audit"][-1]["hash"])
        emit("done", res["status"])
        after_decision(run_id)
    except Exception as ex:  # never leave a run hanging: fail safe to Escalated
        with db() as c:
            c.execute(
                "UPDATE runs SET status='Escalated', result=? WHERE id=?",
                (
                    json.dumps(
                        dict(
                            status="Escalated",
                            findings=[],
                            vendor_message="Internal error; routed to a person.",
                            error=str(ex),
                            audit=[],
                            audit_ok=True,
                        )
                    ),
                    run_id,
                ),
            )
        emit("done", "Escalated (internal error: %s)" % ex)


def page(body, nav=""):
    return render_template("layout.html", body=body, nav=nav)


def tpl(_t, **k):
    return render_template(_t, **k)


@app.route("/")
def dashboard():
    q = request.args.get("status")
    s = (request.args.get("s") or "").strip()
    pg = max(1, int(request.args.get("page", 1) or 1))
    PER = 25
    where, args = [], []
    if q:
        where.append("status=?")
        args.append(q)
    if s:
        where.append("(name LIKE ? OR id LIKE ?)")
        args += [f"%{s}%", f"%{s}%"]
    with db() as c:
        rows = c.execute(
            "SELECT id,created,name,country,status,tier,resubmit_of,result FROM runs"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY created DESC LIMIT ? OFFSET ?",
            (*args, PER + 1, (pg - 1) * PER),
        ).fetchall()
        counts = dict(c.execute("SELECT status,COUNT(*) FROM runs GROUP BY status").fetchall())
    more = len(rows) > PER
    rows = rows[:PER]

    def _why(r):  # one-line reason shown in the history table
        try:
            t = (json.loads(r["result"]) or {}).get("summary", "") if r["result"] else ""
        except ValueError:
            t = ""
        return (t[:140] + "...") if len(t) > 140 else t

    rows = [{**dict(r), "why": _why(r)} for r in rows]
    total = sum(counts.values())
    import collections, statistics

    with db() as c:
        allr = c.execute("SELECT id, status, tier, result, resubmit_of, created FROM runs").fetchall()
        revs = c.execute("SELECT run_id, reviewer, decision FROM reviews").fetchall()
    rr = [json.loads(r["result"]) for r in allr if r["result"]]
    ws = sorted(x.get("work_secs") for x in rr if x.get("work_secs") is not None)
    med = statistics.median(ws) if ws else 0
    p90 = ws[int(0.9 * (len(ws) - 1))] if ws else 0
    reviewed = {x["run_id"] for x in revs}
    roots = {}
    for r in allr:
        rt = r["id"]
        seen = set()
        byid = {x["id"]: x for x in allr}
        while byid.get(rt) and byid[rt]["resubmit_of"] and rt not in seen:
            seen.add(rt)
            rt = byid[rt]["resubmit_of"]
        roots.setdefault(rt, []).append(r)
    first_pass = [min(v, key=lambda x: x["created"]) for v in roots.values()]
    fp_rate = (
        (sum(1 for r in first_pass if r["status"] == "Approved") / len(first_pass) * 100) if first_pass else 0
    )
    avg_rounds = (sum(len(v) for v in roots.values()) / len(roots)) if roots else 0
    touchless = {}
    for r in allr:
        t = touchless.setdefault(r["tier"] or "-", [0, 0])
        t[1] += 1
        t[0] += r["status"] == "Approved" and r["id"] not in reviewed
    stp = (sum(v[0] for v in touchless.values()) / total * 100) if total else 0
    esc_rev = [x for x in revs]
    confirmed = sum(1 for x in esc_rev if x["decision"] in ("Rejected", "Pending"))
    esc_prec = (confirmed / len(esc_rev) * 100) if esc_rev else None
    tm = [med]
    why = collections.Counter(f["rule"] for r in rr for f in r.get("findings", []))
    top = [(k, v, engine.RULES[k][1]) for k, v in why.most_common(5)]
    skipped = sum(1 for r in rr if any(a.get("event") == "paid_check_skipped" for a in r.get("audit", [])))
    saved = (
        counts.get("Approved", 0) * 25
        + counts.get("Rejected", 0) * 17
        + counts.get("Pending", 0) * 7
        + counts.get("Escalated", 0) * 17
    )
    body = tpl(
        "dashboard.html",
        rows=rows,
        more=more,
        pg=pg,
        s=s,
        q=q,
        counts=counts,
        stp=stp,
        fp_rate=fp_rate,
        avg_rounds=avg_rounds,
        med=med,
        p90=p90,
        esc_prec=esc_prec,
        touchless=touchless,
        top=top,
        skipped=skipped,
        saved=saved,
        tm=tm,
        ts=lambda t: time.strftime("%d %b %H:%M", time.localtime(t)),
    )
    return page(body, "d")


SCENARIOS = (
    json.load(open(os.path.join(HERE, "data", "demo", "scenarios.json")))
    if os.path.exists(os.path.join(HERE, "data", "demo", "scenarios.json"))
    else {}
)


# What each demo scenario shows and the result to expect (used by the public /guide page).
GUIDE = {
    "happy": ("Everything matches and the registry says Active.", "Approved, with no human involved"),
    "typo": ("GSTIN has one wrong character, so its check digit fails.", "Pending: vendor gets an email saying exactly what to re-copy"),
    "photo": ("A tilted phone photo of the certificate is still read correctly.", "Approved"),
    "blur": ("The photo is too blurry to read, so we ask for a re-upload instead of guessing.", "Pending: asks for a clearer photo"),
    "cancelled": ("The government registry says this GSTIN is cancelled.", "Rejected, with the reason"),
    "third": ("The cancelled cheque is in a different company's name.", "Escalated to a human reviewer"),
    "bankchange": ("An existing vendor changes bank details (a classic fraud pattern).", "Escalated, high risk: needs a call-back plus two different approvers (use a reviewer login, then a second reviewer)"),
    "retired": ("The bank merged and the old IFSC code no longer exists.", "Pending: vendor asked for the new IFSC"),
    "outage": ("The GST registry is down during the check.", "Pending: never approved just because a check could not run"),
}
STAFF_ONLY = ("bankchange", "outage")  # these need a switch on the staff form, so use the staff scenario buttons


@app.route("/guide")
def guide():
    """Public page: every scenario, what to expect, and its sample documents, so anyone can run them without asking us."""
    cards = []
    for k, v in SCENARIOS.items():
        why, expect = GUIDE.get(k, ("", ""))
        fl = "".join(
            f'<li><a href="/guide/file/{k}/{n}">{n.replace("_", " ")}</a></li>' for n in v.get("files", {})
        )
        vals = "".join(
            f"<li>{a}: <code>{escape(str(b))}</code></li>" for a, b in v["form"].items() if b not in ("", None)
        )
        how = "Staff sign-in, New vendor, click this scenario." if k in STAFF_ONLY else "Click this scenario in New vendor, or use the vendor portal with the files and values below."
        cards.append(
            f"<div class=card><b>{escape(v['title'])}</b><p>{escape(why)}<br><b>Expect:</b> {escape(expect)}</p><small>{how}</small>"
            f"<details><summary>Sample documents and form values</summary><ul>{fl}</ul><ul>{vals}</ul></details></div>"
        )
    body = (
        "<h1>Try it: demo guide</h1><div class=card><b>Fastest way:</b> sign in as staff, open <b>New vendor</b> and click a scenario. "
        "It fills the form and attaches the documents for you; then watch the live run page.<br><br>"
        "<b>As a vendor:</b> use the <a href='/portal'>vendor portal</a> with the sample files below. "
        "<br><br><small>All people, companies and documents here are synthetic. Running one scenario twice is flagged as a duplicate vendor on purpose; an admin can press Reset demo data.</small>"
        "<p><a href='/login'>Staff sign-in</a></p></div>"
        "<div class=card><h2>Try your own vendor</h2><p>You are not limited to the scenarios. Sign in as staff, open <b>New vendor</b> and type any vendor. "
        "The result is worked out from what you type, not looked up from a list.</p><ul>"
        "<li>Open <b>Demo controls</b> at the bottom of the form and tick <b>Pretend the registries already hold this vendor</b>, otherwise the (simulated) government registries will not know your invented vendor and it will be held, asking for documents.</li>"
        "<li><b>GSTIN</b> must be 15 characters with a correct last character. Use the helper below to make one.</li>"
        "<li><b>PAN</b>: 5 letters, 4 digits, 1 letter. The 4th letter says who the holder is (C for a company) and the 5th letter should be the first letter of the name. Example: ABCCM1234F for Meridian Logistics Private Limited.</li>"
        "<li><b>IFSC</b> must be a real bank code. The sample one from a scenario works (for example KKBK0RTGSMI).</li>"
        "<li>Try breaking things: change one digit, give a wrong PAN, use a bad IFSC, set spend above 50 lakh, submit the same vendor twice, or tick <b>GST portal down</b>. Each gives a specific reason.</li></ul>"
        "<p><b>GSTIN helper</b> (state code and PAN in, valid GSTIN out):<br>"
        "<input id=gs placeholder='27' size=3 maxlength=2> <input id=gp placeholder='ABCCM1234F' size=12 maxlength=10> <button type=button id=gb style='width:auto;padding:8px 14px;margin:0'>Make GSTIN</button> <b id=go></b></p>"
        "<script>document.getElementById('gb').onclick=function(){fetch('/guide/gstin?state='+encodeURIComponent(document.getElementById('gs').value)+'&pan='+encodeURIComponent(document.getElementById('gp').value)).then(function(r){return r.text()}).then(function(t){document.getElementById('go').textContent=t})}</script></div>"
        + "".join(cards)
    )
    return render_template("portal_layout.html", body=body)


@app.route("/guide/gstin")
def guide_gstin():
    st = (request.args.get("state") or "").strip()
    pan = (request.args.get("pan") or "").strip().upper()
    if not (len(st) == 2 and st.isdigit() and len(pan) == 10 and pan.isalnum()):
        return "Enter a 2-digit state code (for example 27) and a 10-character PAN."
    base = st + pan + "1Z"
    return base + V.gstin_check_char(base)


@app.route("/guide/file/<scenario>/<kind>")
def guide_file(scenario, kind):
    f = (SCENARIOS.get(scenario, {}).get("files") or {}).get(kind)  # only files listed in scenarios.json can be served
    if not f:
        abort(404)
    p = os.path.join(HERE, f)
    return send_from_directory(os.path.dirname(p), os.path.basename(p))


@app.route("/new")
def new():
    prefill = {}
    if request.args.get("from"):
        with db() as c:
            r = c.execute("SELECT sub FROM runs WHERE id=?", (request.args["from"],)).fetchone()
        if r:
            prefill = dec(r["sub"])
    body = tpl(
        "new.html",
        p=type("P", (dict,), {"__getattr__": lambda s, k: s.get(k)})(
            prefill or _scenario_prefill(request.args.get("scenario"))
        ),
        sc=SCENARIOS,
    )
    return page(body, "n")


def _scenario_prefill(k):
    s = SCENARIOS.get(k or "")
    return dict(s["form"], files=s.get("files") or {}) if s else {}


_HITS = collections.defaultdict(list)
RATE_MAX, RATE_WINDOW = int(os.environ.get("PORTAL_RATE_MAX", "15")), 3600


@app.before_request
def _portal_rate_limit():
    """Public submit endpoint: N submissions per IP per hour (in-memory; production would use the edge/WAF plus CAPTCHA)."""
    if request.method == "POST" and request.path == "/portal/submit":
        ip, now = request.remote_addr or "?", time.time()
        _HITS[ip] = [t for t in _HITS[ip] if now - t < RATE_WINDOW]
        if len(_HITS[ip]) >= RATE_MAX:
            abort(429, "Too many submissions from this address. Please try again later.")
        _HITS[ip].append(now)


@app.route("/submit", methods=["POST"])
def submit():
    security.require("admin", "reviewer")
    return _handle_submit(False)


def _handle_submit(vendor):
    f = request.form

    def fail(html, code):
        return (_portal(html) if vendor else page(html, "n")), code

    resub = None
    if (
        vendor
    ):  # a vendor may only resubmit via its own private link token; never trust a raw run id from the form
        with db() as c_:
            rr_ = c_.execute("SELECT id FROM runs WHERE token=?", (f.get("resubmit_token") or "",)).fetchone()
        resub = rr_["id"] if rr_ else None
    else:
        resub = f.get("resubmit_of") or None
    CAP = {"address": 400}
    sub = {
        k: f.get(k, "").strip()[: CAP.get(k, 150)]
        for k in (
            "country",
            "legal_name",
            "gstin",
            "pan",
            "cin",
            "state",
            "ifsc",
            "account",
            "ein",
            "vat",
            "address",
            "bank",
            "email",
            "udyam",
            "phone",
        )
    }
    try:
        sub["expected_annual_value"] = max(
            0.0, float(str(f.get("expected_annual_value") or 0).replace(",", ""))
        )
    except ValueError:
        sub["expected_annual_value"] = 0.0
    sub["no_gst"] = bool(f.get("no_gst")) and not sub["gstin"]
    sub["bank_change"] = bool(f.get("bank_change")) and not vendor
    for d in ("gst", "sanctions", "bank"):
        sub[f"down_{d}"] = bool(f.get(f"down_{d}")) and not vendor and security.DEMO
    sub["demo_registry"] = bool(f.get("demo_registry")) and not vendor and security.DEMO
    if vendor:
        sub["expected_annual_value"] = None
        sub["source"] = "vendor_portal"
    rid = uuid.uuid4().hex[:10]
    files = {}
    for kind in ("gst_cert", "cheque", "pan_card", "udyam_cert"):
        up = request.files.get(kind)
        if up and up.filename:
            ext = os.path.splitext(up.filename)[1].lower()
            if ext not in ALLOWED:
                return fail(
                    f'<div class=card><h2>Unsupported file</h2>{kind}: please upload a PDF, PNG or JPG. <a href="javascript:history.back()">Go back</a></div>',
                    400,
                )
            head = up.stream.read(12)
            up.stream.seek(0)
            okmagic = head.startswith(b"%PDF") or head.startswith(b"\x89PNG") or head[:3] == b"\xff\xd8\xff"
            if not okmagic:
                return fail(
                    f'<div class=card><h2>File not recognised</h2>{kind}: the file content is not a real PDF/PNG/JPG (renamed file?). <a href="javascript:history.back()">Go back</a></div>',
                    400,
                )
            up.stream.seek(0, 2)
            size = up.stream.tell()
            up.stream.seek(0)
            if size > MAX_FILE:
                return fail(
                    f'<div class=card><h2>File too large</h2>{kind}: the limit is 12 MB. Please upload a smaller photo or PDF. <a href="javascript:history.back()">Go back</a></div>',
                    413,
                )
            if size == 0:
                return fail(
                    f'<div class=card><h2>Empty file</h2>{kind}: the file you chose is empty. <a href="javascript:history.back()">Go back</a></div>',
                    400,
                )
            p = os.path.join(UP, f"{rid}_{kind}{ext}")
            up.save(p)
            os.chmod(p, 0o600)
            files[kind] = p
    sc = _scenario_prefill(f.get("scenario")) if not vendor else {}
    for kind, p in (sc.get("files") or {}).items():
        if kind not in files and os.path.exists(os.path.join(HERE, p)):
            files[kind] = os.path.join(HERE, p)
    if resub:  # a correction keeps the documents already supplied unless new ones are uploaded
        with db() as c_:
            pr_ = c_.execute("SELECT sub FROM runs WHERE id=?", (resub,)).fetchone()
        for kind, p in ((dec(pr_["sub"]) if pr_ and pr_["sub"] else {}) or {}).get("files", {}).items():
            if kind not in files and os.path.exists(p):
                files[kind] = p
    sub["files"] = files
    with db() as c:
        dup = None
        if not resub:
            for r_ in c.execute(
                "SELECT id, token, sub FROM runs WHERE status='Running' AND created>?", (time.time() - 120,)
            ):
                s_ = dec(r_["sub"]) or {}
                if (
                    s_.get("legal_name") == sub["legal_name"]
                    and s_.get("gstin") == sub["gstin"]
                    and s_.get("pan") == sub["pan"]
                ):
                    dup = r_
                    break
        if dup:
            return redirect(
                f"/portal/s/{dup['token']}" if vendor else url_for("run_view", rid=dup["id"])
            )  # double-click / double-submit: show the run already in progress
        tok = uuid.uuid4().hex
        c.execute(
            "INSERT INTO runs(id,created,name,country,status,tier,sub,result,resubmit_of,token) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                time.time(),
                sub["legal_name"],
                sub["country"],
                "Running",
                None,
                enc(sub),
                None,
                resub,
                tok,
            ),
        )
    threading.Thread(target=process, args=(rid,), daemon=True).start()
    if vendor:
        return redirect(f"/portal/s/{tok}")
    return redirect(url_for("run_view", rid=rid))


# ---------------------------------------------------------------- vendor portal (public, no internal detail) ------------------


def _portal(body):
    return render_template("portal_layout.html", body=body)


@app.route("/portal")
def portal():
    p = {}
    tok = request.args.get("resubmit")
    if tok:
        with db() as c:
            r = c.execute("SELECT id, sub FROM runs WHERE token=?", (tok,)).fetchone()
        if r:
            p = dec(r["sub"])
            p["_from"] = tok
    body = tpl(
        "portal.html",
        p=type("P", (dict,), {"__getattr__": lambda s, k: s.get(k)})(p),
    )
    return _portal(body)


@app.route("/portal/submit", methods=["POST"])
def portal_submit():
    return _handle_submit(True)


def _vendor_view(r):
    res = json.loads(r["result"]) if r["result"] else None
    st = r["status"]
    if st == "Running" or not res:
        return dict(
            label="Checking your documents",
            cls="warn",
            message="This takes about a minute. You can leave this page open.",
            fixes=[],
            done=False,
        )
    fixes = [
        f["fix"] if f["rule"] != "R25" else f["detail"]
        for f in res.get("findings", [])
        if f["outcome"] == "P" and f.get("fix")
    ]
    fixes = list(dict.fromkeys(fixes))
    label, cls = {
        "Approved": ("Approved", "ok"),
        "Pending": ("Action needed", "warn"),
        "Escalated": ("Under review", "warn"),
        "Rejected": ("Not approved", "bad"),
    }.get(st, (st, "warn"))
    return dict(
        label=label, cls=cls, message=res.get("vendor_message", ""), fixes=fixes, done=True, status=st
    )


@app.route("/portal/api/<tok>")
def portal_api(tok):
    with db() as c:
        r = c.execute("SELECT * FROM runs WHERE token=?", (tok,)).fetchone()
    if not r:
        abort(404)
    return jsonify(_vendor_view(r))


@app.route("/portal/s/<tok>")
def portal_status(tok):
    with db() as c:
        r = c.execute("SELECT * FROM runs WHERE token=?", (tok,)).fetchone()
    if not r:
        abort(404)
    body = tpl(
        "portal_status.html",
        name=r["name"],
        tok=tok,
    )
    return _portal(body)


@app.route("/file/<rid>/<kind>")
def file_view(rid, kind):
    with db() as c:
        r = c.execute("SELECT sub FROM runs WHERE id=?", (rid,)).fetchone()
    p = ((dec(r["sub"]).get("files") or {}).get(kind)) if r else None
    if not p or not os.path.exists(p) or kind not in ("gst_cert", "cheque", "pan_card", "udyam_cert"):
        abort(404)
    return send_from_directory(os.path.dirname(p), os.path.basename(p))


@app.route("/reset", methods=["POST"])
def reset():
    security.require("admin")
    with db() as c:
        c.executescript("DELETE FROM runs; DELETE FROM events; DELETE FROM reviews; DELETE FROM outbox; DELETE FROM settings WHERE k='clock_offset_days';")
    engine.Registries.OVERRIDES.clear()  # the drift demo changes a registry in memory; a reset must undo that too
    return redirect("/")


@app.route("/api/run/<rid>")
def api_run(rid):
    with db() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        ev = [
            dict(seq=e["seq"], stage=e["stage"], msg=e["msg"])
            for e in c.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (rid,))
        ]
        rv = [
            dict(t=x["t"], reviewer=x["reviewer"], decision=x["decision"], reason=x["reason"])
            for x in c.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY t", (rid,))
        ]
    res = json.loads(r["result"]) if r["result"] else None
    if res:
        res["docs_present"] = list((dec(r["sub"]).get("files") or {}).keys())
    return jsonify(
        status=r["status"],
        tier=r["tier"],
        events=ev,
        result=res,
        reviews=rv,
        name=r["name"],
        resubmit_of=r["resubmit_of"],
    )


@app.route("/run/<rid>")
def run_view(rid):
    body = tpl(
        "run_view.html",
        rid=rid,
        order=list(LABEL),
        label=LABEL,
    )
    return page(body)


@app.route("/review", methods=["GET"])
def review():
    security.require("admin", "reviewer")
    with db() as c:
        rows = c.execute(
            "SELECT id,created,name,tier,result,sub FROM runs WHERE status='Escalated' ORDER BY created"
        ).fetchall()
        appr = {}
        for x in c.execute("SELECT run_id, reviewer FROM reviews WHERE decision='Approved'"):
            appr.setdefault(x["run_id"], []).append(x["reviewer"])
        masters = [
            (dec(r["sub"]), r["id"])
            for r in c.execute("SELECT id, sub FROM runs WHERE status='Approved'")
            if r["sub"]
        ]
    items = []
    for r in rows:
        res = json.loads(r["result"] or "{}")
        s = dec(r["sub"]) or {}
        rules = {f["rule"] for f in res.get("findings", [])}
        master = (
            next((m for m, i in masters if m.get("gstin") and m.get("gstin") == s.get("gstin")), None)
            if "R27" in rules
            else None
        )
        items.append(
            dict(
                id=r["id"],
                name=r["name"],
                tier=r["tier"],
                age=int((_now() - r["created"]) / 60),
                approvals=appr.get(r["id"], []),
                callback="R27" in rules,
                master_email=(master or {}).get("email"),
                master_phone=(master or {}).get("phone"),
                new_email=s.get("email"),
                why=[f"{f['rule']}: {f['detail']}" for f in res.get("findings", []) if f["outcome"] == "E"],
            )
        )
    body = tpl(
        "review.html",
        items=items,
    )
    return page(body, "r")


@app.route("/review/<rid>", methods=["POST"])
def review_post(rid):
    security.require("reviewer", "admin")
    d = request.form.get("decision")
    reason = (request.form.get("reason") or "").strip()
    if d not in ("Approved", "Pending", "Rejected") or len(reason) < 5:
        abort(400, "a decision and a reason (5+ characters) are required")
    with db() as c:
        r = c.execute("SELECT status, tier, result FROM runs WHERE id=?", (rid,)).fetchone()
        if not r:
            abort(404)
        if r["status"] != "Escalated":
            abort(409, "only escalated cases can be decided")
        prior = {
            x["reviewer"]
            for x in c.execute("SELECT reviewer FROM reviews WHERE run_id=? AND decision='Approved'", (rid,))
        }
        if g.user in prior:
            abort(409, "you already approved this case; a second, different approver is required")
        if (
            d == "Approved"
            and "R27" in {f["rule"] for f in json.loads(r["result"] or "{}").get("findings", [])}
            and not request.form.get("callback_done")
        ):
            abort(400, "confirm the call-back to the number on file before approving a bank-detail change")
        final = d
        if d == "Approved" and r["tier"] == "High" and not prior:
            final = "Escalated"  # High risk: two distinct approvers (maker-checker)
        c.execute("INSERT INTO reviews VALUES(?,?,?,?,?)", (rid, time.time(), g.user, d, reason))
        res = json.loads(r["result"] or "{}")
        ent = engine.Audit.append(
            res.setdefault("audit", []),
            "decision",
            "reviewer_decision",
            reviewer=g.user,
            decision=d,
            reason=reason,
            resulting_status=final,
        )
        res["audit_ok"] = engine.Audit.verify(res["audit"])
        c.execute("UPDATE runs SET status=?, result=? WHERE id=?", (final, json.dumps(res, default=str), rid))
    security.anchor(rid, ent["hash"])
    return redirect("/review")


def purge(days):
    """Retention: delete uploaded documents and strip personal/bank data from closed runs older than `days` (keeps outcome + audit chain)."""
    cut = time.time() - days * 86400
    n = 0
    with db() as c:
        for r in c.execute(
            "SELECT id, sub, name, country FROM runs WHERE created<? AND status IN ('Approved','Rejected','Pending')",
            (cut,),
        ).fetchall():
            s = dec(r["sub"]) if r["sub"] else None
            if not s or s.get("_purged"):
                continue
            for p in (s.get("files") or {}).values():
                try:
                    if os.path.commonpath([os.path.abspath(p), UP]) == UP:
                        os.remove(p)
                except Exception:
                    pass
            c.execute(
                "UPDATE runs SET sub=? WHERE id=?",
                (enc(dict(legal_name=s.get("legal_name"), country=s.get("country"), _purged=True)), r["id"]),
            )
            n += 1
    return n


@app.route("/admin/purge", methods=["POST"])
def admin_purge():
    security.require("admin")
    n = purge(int(request.form.get("days") or os.environ.get("RETENTION_DAYS", 90)))
    return page(
        f"<div class=card><h2>Retention purge</h2>{n} closed run(s) had documents and personal data removed. <a href='/'>Back</a></div>"
    )


def recover():
    """After a restart, re-queue runs that were mid-flight so none hangs on 'Running' forever."""
    with db() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM runs WHERE status='Running'")]
        for i in ids:
            c.execute("DELETE FROM events WHERE run_id=?", (i,))
    for i in ids:
        threading.Thread(target=process, args=(i,), daemon=True).start()
    return len(ids)


@app.route("/eval")
def evals():
    def j(n):
        try:
            return json.load(open(os.path.join(HERE, "data", "real", n)))
        except OSError:
            return None

    e, s, g, ch, q, inj, chr_ = (
        j("eval_engine.json"),
        j("eval_sanctions_real.json"),
        j("eval_docs_gst.json"),
        j("eval_docs_cheques.json"),
        j("eval_quality_rows.json"),
        j("eval_injection.json"),
        j("eval_cheques_real.json"),
    )
    cva = j("eval_cheque_all.json")
    cvs = None
    if cva:
        import collections

        names_ = {
            "idrbt_scan": "Scans (public IDRBT-derived set, 4 banks; 87 are one Axis form)",
            "hf_synth": "Synthetic cheques (bank known, no IFSC label)",
            "real_photo": "Real phone/web photos (6 labelled, 6 not)",
        }

        def _fmt(c):
            return ", ".join(f"{v} {k}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])) or "n/a"

        cvs = []
        for sg in names_:
            rr = [r for r in cva if r.get("seg") == sg and "error" not in r]
            cc = {
                k: collections.Counter(r["cases"][k]["verdict"] for r in rr if k in r["cases"])
                for k in ("true", "wrong_bank", "same_bank_other_branch")
            }
            cvs.append(
                dict(
                    name=names_[sg],
                    n=len(rr),
                    true=_fmt(cc["true"]),
                    wb=_fmt(cc["wrong_bank"]),
                    br=_fmt(cc["same_bank_other_branch"]),
                )
            )
    body = tpl(
        "evals.html",
        e=e,
        s=s,
        g=g,
        ch=ch,
        q=q,
        inj=inj,
        chr_=chr_,
        cvs=cvs,
    )
    return page(body, "e")


# ---------------------------------------------------------------- vendor communication, pending clock, exports, re-verification ----
def _setup_ops():
    with db() as c:
        c.executescript(
            """CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, t REAL, to_addr TEXT, subject TEXT, body TEXT, sent INTEGER DEFAULT 0, UNIQUE(run_id, kind));
            CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);"""
        )
        cols = [r[1] for r in c.execute("PRAGMA table_info(runs)")]
        if "status_t" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN status_t REAL")


_setup_ops()
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def _now():
    with db() as c:
        r = c.execute("SELECT v FROM settings WHERE k='clock_offset_days'").fetchone()
    return time.time() + (float(r["v"]) * 86400 if r else 0)


def notify(run_id, kind, subject, body):
    """Draft (and, when SMTP_HOST is configured, send) a vendor email. One per (run, kind): idempotent, so reminders never double-send."""
    with db() as c:
        r = c.execute("SELECT sub FROM runs WHERE id=?", (run_id,)).fetchone()
        s = dec(r["sub"]) if r and r["sub"] else {}
        to = (s or {}).get("email") or ""
        try:
            c.execute(
                "INSERT INTO outbox(run_id,kind,t,to_addr,subject,body) VALUES(?,?,?,?,?,?)",
                (run_id, kind, _now(), to, subject, body),
            )
        except sqlite3.IntegrityError:
            return False
    if os.environ.get("SMTP_HOST") and to:
        try:
            import smtplib
            from email.message import EmailMessage

            # MAIL_REDIRECT_TO: send every email to one safe inbox instead of the vendor (the real address goes in the subject),
            # so a demo with made-up vendor addresses never mails strangers.
            redirect_to = os.environ.get("MAIL_REDIRECT_TO", "").strip()
            m = EmailMessage()
            m["From"] = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or "onboarding@example.com"
            m["To"] = redirect_to or to
            m["Subject"] = f"[to: {to}] {subject}" if redirect_to else subject
            m.set_content(body)
            port = int(os.environ.get("SMTP_PORT", 587))
            with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as sm:
                if os.environ.get("SMTP_STARTTLS", "1") == "1":
                    sm.starttls()
                if os.environ.get("SMTP_USER"):
                    sm.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
                sm.send_message(m)
            with db() as c:
                c.execute("UPDATE outbox SET sent=1 WHERE run_id=? AND kind=?", (run_id, kind))
        except Exception as ex:
            print("mail failed:", ex)
    return True


def _set_status(run_id, status):
    with db() as c:
        c.execute("UPDATE runs SET status_t=? WHERE id=?", (_now(), run_id))


def after_decision(run_id):
    """Called when a run reaches a final system status: draft the right vendor email."""
    with db() as c:
        r = c.execute("SELECT name, status, token, result FROM runs WHERE id=?", (run_id,)).fetchone()
    if not r or not r["result"]:
        return
    res = json.loads(r["result"])
    link = f"{BASE_URL}/portal/s/{r['token']}"
    st = r["status"]
    _set_status(run_id, st)
    if st == "Approved":
        notify(
            run_id,
            "approved",
            "You are registered as a vendor",
            f"Hello,\n\n{res.get('vendor_message','')}\n\nStatus: {link}\n",
        )
    elif st == "Pending" and {
        f["rule"] for f in res.get("findings", []) if f.get("outcome") in ("P", "E", "R")
    } == {"R26"}:
        notify(
            run_id,
            "pending_outage",
            "Your vendor registration is being verified",
            f"Hello,\n\n{res.get('vendor_message','')}\n\nStatus: {link}\n",
        )
    elif st == "Pending":
        notify(
            run_id,
            "pending",
            "Action needed on your vendor registration",
            f"Hello,\n\n{res.get('vendor_message','')}\n\nCorrect and resubmit: {BASE_URL}/portal?resubmit={r['token']}\nWe will remind you on day 3 and day 7, and close the request on day 14 if we hear nothing.\n",
        )
    elif st == "Rejected":
        notify(run_id, "rejected", "Your vendor registration", f"Hello,\n\n{res.get('vendor_message','')}\n")
    elif st == "Escalated":
        notify(
            run_id,
            "escalated",
            "Your vendor registration is under review",
            f"Hello,\n\n{res.get('vendor_message','')}\n\nStatus: {link}\n",
        )


PENDING_CLOCK = dict(remind=(3, 7), close=14)


def _retry_outage(rid):
    """A run held only because a registry was unreachable (R26) is re-run by the system itself; the vendor has nothing to do."""
    with db() as c:
        row = c.execute("SELECT sub, result, status FROM runs WHERE id=?", (rid,)).fetchone()
    if not row or row["status"] != "Pending":
        return False
    res0 = json.loads(row["result"] or "{}")
    blocking = {f["rule"] for f in res0.get("findings", []) if f.get("outcome") in ("P", "E", "R")}
    if blocking != {"R26"}:
        return False
    sub = dec(row["sub"])
    for d in ("gst", "sanctions", "bank", "pan", "mca", "udyam"):
        sub.pop(
            f"down_{d}", None
        )  # the outage is assumed over on retry; a real one simply fails again and stays Pending
    try:
        res = engine.run(sub, _registries(sub), emit=lambda *a: None, existing=[])
    except Exception:
        return False
    res["audit"] = (res0.get("audit") or []) + res.get("audit", [])
    with db() as c:
        c.execute(
            "UPDATE runs SET status=?, tier=?, result=?, sub=?, status_t=? WHERE id=? AND status='Pending'",
            (res["status"], res["tier"], json.dumps(res, default=str), enc(sub), _now(), rid),
        )
    after_decision(rid)
    return True


def sweep():
    """Pending clock: reminder on day 3 and 7, auto-close on day 14. Idempotent; safe to call often. Returns what it did."""
    done = []
    now = _now()
    with db() as c:
        rows = c.execute("SELECT id, token, status_t, created FROM runs WHERE status='Pending'").fetchall()
    for r in rows:
        if _retry_outage(r["id"]):
            done.append((r["id"], "auto_retry"))
            continue
        age = (now - (r["status_t"] or r["created"])) / 86400
        link = f"{BASE_URL}/portal?resubmit={r['token']}"
        for d in PENDING_CLOCK["remind"]:
            if age >= d and notify(
                r["id"],
                f"reminder_day{d}",
                "Reminder: your vendor registration needs a fix",
                f"Hello,\n\nThis is a reminder (day {d}). Please correct and resubmit: {link}\n",
            ):
                done.append((r["id"], f"reminder_day{d}"))
        if age >= PENDING_CLOCK["close"]:
            with db() as c:
                res = json.loads(
                    c.execute("SELECT result FROM runs WHERE id=?", (r["id"],)).fetchone()["result"] or "{}"
                )
                ent = engine.Audit.append(
                    res.setdefault("audit", []),
                    "decision",
                    "auto_closed",
                    reason="no vendor response in 14 days",
                )
                res["audit_ok"] = engine.Audit.verify(res["audit"])
                c.execute(
                    "UPDATE runs SET status='Closed', result=? WHERE id=?",
                    (json.dumps(res, default=str), r["id"]),
                )
            security.anchor(r["id"], ent["hash"])
            notify(
                r["id"],
                "closed",
                "Your vendor registration request was closed",
                "We did not hear back, so we closed this request. You can start again any time at "
                + BASE_URL
                + "/portal\n",
            )
            done.append((r["id"], "closed"))
    return done


def _sweeper_loop():
    while True:
        time.sleep(int(os.environ.get("SWEEP_SECONDS", 300)))
        try:
            sweep()
        except Exception as ex:
            print("sweep:", ex)


@app.route("/admin/advance", methods=["POST"])
def admin_advance():
    security.require("admin")
    if not security.DEMO:
        abort(403, "time travel is a demo-only control")
    d = float(request.form.get("days") or 1)
    with db() as c:
        cur = c.execute("SELECT v FROM settings WHERE k='clock_offset_days'").fetchone()
        v = (float(cur["v"]) if cur else 0) + d
        c.execute("INSERT OR REPLACE INTO settings VALUES('clock_offset_days', ?)", (str(v),))
    done = sweep()
    return page(
        f"<div class=card><h2>Clock advanced by {d:g} day(s) (demo)</h2><p>Simulated time is now +{v:g} days. Actions taken: {len(done)}.</p><ul>"
        + "".join(f"<li>{i}: {k}</li>" for i, k in done)
        + "</ul><a href='/outbox'>See emails</a> · <a href='/'>Dashboard</a></div>"
    )


@app.route("/outbox")
def outbox():
    security.require("admin", "reviewer", "ap")
    with db() as c:
        rows = c.execute(
            "SELECT o.*, r.name FROM outbox o LEFT JOIN runs r ON r.id=o.run_id ORDER BY o.id DESC LIMIT 100"
        ).fetchall()
    body = tpl(
        "outbox.html",
        rows=rows,
    )
    return page(body, "o")


@app.route("/export/vendors.csv")
def export_vendors():
    security.require("admin", "ap")
    import csv, io

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "vendor_id",
            "legal_name",
            "gstin",
            "pan",
            "ifsc",
            "account_last4",
            "risk_tier",
            "tds",
            "msme_terms",
            "gst_mode",
            "verified_as_of",
            "rules_version",
            "flags",
        ]
    )
    with db() as c:
        rows = c.execute("SELECT id, name, sub, result FROM runs WHERE status='Approved'").fetchall()
    for r in rows:
        s = dec(r["sub"]) or {}
        p = (json.loads(r["result"] or "{}")).get("profile") or {}
        w.writerow(
            [
                r["id"],
                r["name"],
                s.get("gstin"),
                s.get("pan"),
                s.get("ifsc"),
                (s.get("account") or "")[-4:],
                p.get("risk_tier"),
                p.get("tds"),
                p.get("msme_terms") or "",
                p.get("gst_mode"),
                p.get("verified_as_of"),
                p.get("rules_version"),
                "; ".join(p.get("flags") or []),
            ]
        )
    from flask import Response

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=approved_vendors.csv"},
    )


@app.route("/export/<rid>.json")
def export_one(rid):
    security.require("admin", "ap", "reviewer")
    with db() as c:
        r = c.execute("SELECT name, status, result FROM runs WHERE id=?", (rid,)).fetchone()
    if not r:
        abort(404)
    res = json.loads(r["result"] or "{}")
    return jsonify(
        vendor=r["name"],
        status=r["status"],
        profile=res.get("profile"),
        findings=[
            dict(rule=f["rule"], outcome=f["outcome"], detail=f["detail"]) for f in res.get("findings", [])
        ],
    )


# demo-only: change a registry status after onboarding, to show periodic re-verification catching drift
@app.route("/admin/drift/<rid>", methods=["POST"])
def admin_drift(rid):
    security.require("admin")
    if not security.DEMO:
        abort(403)
    with db() as c:
        r = c.execute("SELECT sub FROM runs WHERE id=?", (rid,)).fetchone()
    s = dec(r["sub"]) if r else None
    if not s:
        abort(404)
    engine.Registries.OVERRIDES[s["gstin"]] = {"gst_status": "Cancelled"}
    return redirect(f"/reverify/{rid}")


@app.route("/reverify/<rid>", methods=["GET", "POST"])
def reverify(rid):
    """Periodic re-verification: re-run the registry checks for an approved vendor using the stored submission and documents; report drift."""
    security.require("admin", "reviewer")
    with db() as c:
        r = c.execute("SELECT sub, status, result, name FROM runs WHERE id=?", (rid,)).fetchone()
    if not r:
        abort(404)
    if request.method == "GET":
        return page(
            f"<div class=card><h2>Re-verify {escape(r['name'])}</h2><p>Re-runs GST, PAN, MCA status and sanctions with today's registry data and compares with the original approval.</p><form method=post><button>Re-verify now</button></form>"
            + (
                "<form method=post action='/admin/drift/%s' style='margin-top:12px'><button class=sec>Demo: simulate GST cancellation first</button></form>"
                % rid
                if security.DEMO
                else ""
            )
            + "</div>"
        )
    s = dec(r["sub"])
    s["docs"] = json.loads(r["result"] or "{}").get("docs_cache") or s.get("docs") or {}
    s["bank_change"] = False
    res = engine.run(s, _registries(s), existing=[])
    before = r["status"]
    drift = res["status"] != before
    msg = f"<span class='pill {res['status']}'>{res['status']}</span> (was {escape(before)})"
    if drift:
        msg += (
            "<p><b>Status drift detected.</b> "
            + "; ".join(
                str(escape(f["rule"] + ": " + f["detail"]))
                for f in res["findings"]
                if f["outcome"] in ("R", "E", "P")
            )
            + "</p>"
        )
    with db() as c:
        old = json.loads(r["result"] or "{}")
        ent = engine.Audit.append(
            old.setdefault("audit", []), "reverify", "reverified", result=res["status"], drift=drift
        )
        if drift and before == "Approved":
            c.execute(
                "UPDATE runs SET status='Escalated', result=? WHERE id=?", (json.dumps(old, default=str), rid)
            )
            security.anchor(rid, ent["hash"])
        else:
            c.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(old, default=str), rid))
    return page(
        f"<div class=card><h2>Re-verification result</h2>{msg}{'<p>Case moved to the review queue.</p>' if drift and before == 'Approved' else ''}<a href='/run/{rid}'>Back to run</a></div>"
    )


try:
    purge(int(os.environ.get("RETENTION_DAYS", 90)))
    recover()
    threading.Thread(target=_sweeper_loop, daemon=True).start()
except Exception as _e:
    print("startup tasks:", _e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), threaded=True)
