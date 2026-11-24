"""Authentication, CSRF, encryption-at-rest and audit anchoring for the onboarding app.

Prototype scope, stated plainly:
- Users come from the USERS env var ("name:password:role,..."); defaults are DEMO accounts, shown on the login page while DEMO=1. Production: SSO/OIDC.
- Roles: admin (everything, incl. purge/reset), reviewer (decide escalations), ap (read-only dashboard).
- Vendor-submitted personal/bank data is encrypted at rest (Fernet; key from FIELD_KEY or a generated data/.fieldkey). Production: KMS-managed key.
"""

import os, json, time, hmac, hashlib, secrets
from flask import session, request, redirect, abort, g, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
DEMO = os.environ.get("DEMO", "1") == "1"


def _keyfile(name, make):
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        return open(p, "rb").read().strip()
    k = make()
    open(p, "wb").write(k)
    os.chmod(p, 0o600)
    return k


_F = Fernet((os.environ.get("FIELD_KEY") or "").encode() or _keyfile(".fieldkey", Fernet.generate_key))


def enc(obj):
    return "enc:" + _F.encrypt(json.dumps(obj, default=str).encode()).decode()


def dec(s):
    if s is None:
        return None
    if isinstance(s, str) and s.startswith("enc:"):
        return json.loads(_F.decrypt(s[4:].encode()))
    return json.loads(s)  # legacy plaintext rows


def _users():
    raw = (
        os.environ.get("USERS")
        or "admin:demo:admin,reviewer1:demo:reviewer,reviewer2:demo:reviewer,ap1:demo:ap"
    )
    out = {}
    for item in raw.split(","):
        n, pw, role = item.split(":")
        out[n] = (generate_password_hash(pw), role)
    return out


USERS = _users()
PUBLIC_PREFIX = ("/portal", "/login", "/static", "/healthz", "/guide")


def anchor(run_id, head):
    """External append-only anchor of chain heads (production: WORM bucket / transparency log)."""
    with open(os.path.join(DATA, "audit_anchor.log"), "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {run_id} {head}\n")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


LOGIN = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Sign in · Vendor onboarding</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f5f6f8;font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#1c2430}
.box{width:100%;max-width:400px;margin:24px;padding:28px;background:#fff;border:1px solid #e3e6eb;border-radius:14px}
h1{font-size:21px;margin:0 0 4px}p.s{margin:0 0 18px;color:#556;font-size:14px}label{display:block;font-size:14px;color:#445;margin:14px 0 4px}
input{width:100%;padding:11px;border:1px solid #bcc3cf;border-radius:8px;font:inherit}input:focus,button:focus{outline:3px solid #2b59c3;outline-offset:1px}
button{width:100%;margin-top:20px;padding:12px;background:#2b59c3;color:#fff;border:0;border-radius:8px;font:inherit;cursor:pointer}
.err{color:#a00;font-size:14px}.note{margin-top:18px;padding:10px 12px;background:#f1f3f6;border-radius:8px;font-size:13px;color:#445}a{color:#2b59c3}</style>
<div class=box><h1>Vendor onboarding</h1><p class=s>Staff sign-in: dashboard, live runs, review queue.</p>
{% if err %}<div class=err role=alert>{{err}}</div>{% endif %}
<form method=post><input type=hidden name=_csrf value="{{tok}}"><label for=u>User</label><input id=u name=user autofocus autocomplete=username>
<label for=p>Password</label><input id=p name=pw type=password autocomplete=current-password><button>Sign in</button></form>
{% if hint %}<div class=note>{{hint}}</div>{% endif %}
{% if demo %}<div class=note>Demo accounts (password <b>demo</b>): admin, reviewer1, reviewer2, ap1.</div>{% endif %}
<div class=note>Are you a vendor? Go to the <a href="/portal">vendor registration portal</a>.</div>
<div class=note>New here? The <a href="/guide">demo guide</a> lists every scenario, what to expect, and downloadable sample documents.</div></div>"""


def init_app(app):
    app.secret_key = (
        os.environ.get("SECRET_KEY") or _keyfile(".secret", lambda: secrets.token_hex(32).encode()).decode()
    )
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("HTTPS", "0") == "1",
    )

    @app.before_request
    def guard():
        p = request.path
        if (
            request.method == "POST"
        ):  # CSRF on every state-changing request (token or same-origin check for API clients)
            tok = request.form.get("_csrf") or request.headers.get("X-CSRF")
            if not tok or not hmac.compare_digest(tok, session.get("_csrf", "")):
                abort(403, "missing or invalid CSRF token")
        if p.startswith(PUBLIC_PREFIX):
            return
        if "user" not in session:
            return redirect("/login?next=" + p)
        g.user, g.role = session["user"], session["role"]

    @app.after_request
    def headers(r):
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("X-Frame-Options", "DENY")
        r.headers.setdefault("Referrer-Policy", "same-origin")
        r.headers.setdefault("Cache-Control", "no-store")
        r.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:",
        )
        return r

    @app.route("/login", methods=["GET", "POST"])
    def login():
        err = None
        if request.method == "POST":
            u = USERS.get(request.form.get("user", ""))
            time.sleep(0.4)  # slows password guessing
            if u and check_password_hash(u[0], request.form.get("pw", "")):
                session.clear()
                session["user"] = request.form["user"]
                session["role"] = u[1]
                csrf_token()
                nxt = request.args.get("next") or "/"
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
            err = "Wrong user or password."
        return render_template_string(LOGIN, err=err, demo=DEMO and not os.environ.get("USERS"), hint=os.environ.get("LOGIN_HINT", ""), tok=csrf_token())

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect("/login")

    @app.route("/healthz")
    def healthz():
        return "ok"

    app.jinja_env.globals["csrf_token"] = csrf_token


def require(*roles):
    if g.get("role") not in roles:
        abort(403, "your role cannot do this")
