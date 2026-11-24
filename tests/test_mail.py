"""Email delivery test: runs a fake SMTP server in-process and checks that a Pending vendor's email really leaves the app,
goes to the address the vendor typed, and that MAIL_REDIRECT_TO diverts it. No network needed."""
import os, sys, tempfile, threading, socketserver, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["STAGE_DELAY"] = "0"
GOT = []


class H(socketserver.StreamRequestHandler):
    def handle(self):
        w = lambda t: (self.wfile.write((t + "\r\n").encode()), self.wfile.flush())
        w("220 fake"); data = False; buf = []
        for raw in self.rfile:
            l = raw.decode().rstrip("\r\n")
            if data:
                if l == ".":
                    data = False; GOT.append("\n".join(buf)); w("250 ok")
                else:
                    buf.append(l)
                continue
            c = l.upper()
            if c.startswith(("EHLO", "HELO")): w("250 fake")
            elif c == "DATA": data = True; w("354 go")
            elif c == "QUIT": w("221 bye"); return
            else: w("250 ok")


socketserver.ThreadingTCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(SMTP_HOST="127.0.0.1", SMTP_PORT=str(srv.server_address[1]), SMTP_STARTTLS="0", MAIL_FROM="ap@test.in")
import app as A

A.DB = os.path.join(tempfile.mkdtemp(), "t.db"); A.init()
with A.db() as c:
    if "token" not in [r[1] for r in c.execute("PRAGMA table_info(runs)")]:
        c.execute("ALTER TABLE runs ADD COLUMN token TEXT")
A._setup_ops()
ok = True
def check(n, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + n); ok &= bool(cond)

pc = A.app.test_client(); pc.get("/portal")
with pc.session_transaction() as s: pt = s["_csrf"]
form = dict(_csrf=pt, country="IN", legal_name="Test Traders", gstin="27AAAAA0000A1Z5", pan="AAAAA0000A", ifsc="HDFC0000001",
            account="1234567890", expected_annual_value="1", email="vendor@acme.example")
pc.post("/portal/submit", data=form)
for _ in range(60):
    if GOT: break
    time.sleep(0.5)
check("an email was delivered over SMTP", len(GOT) == 1)
check("it went to the vendor's address", GOT and "To: vendor@acme.example" in GOT[0])
with A.db() as c:
    check("outbox marks it sent", c.execute("SELECT sent FROM outbox").fetchone()["sent"] == 1)
GOT.clear(); os.environ["MAIL_REDIRECT_TO"] = "me@demo.example"
form["legal_name"] = "Other Traders"; form["email"] = "stranger@elsewhere.example"; form["_csrf"] = pt
pc.post("/portal/submit", data=form)
for _ in range(60):
    if GOT: break
    time.sleep(0.5)
check("redirect option diverts mail", GOT and "To: me@demo.example" in GOT[0] and "stranger@elsewhere.example" in GOT[0])
print("MAIL TESTS", "PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
