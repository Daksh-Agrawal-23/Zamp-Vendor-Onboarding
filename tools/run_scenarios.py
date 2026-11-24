import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Run every prepared demo scenario end to end through the real web app (temp DB) and print outcomes. Usage: PYTHONPATH=. python3 run_scenarios.py"""
import os, sys, re, json, time, tempfile

os.environ["STAGE_DELAY"] = "0"
import app as A

tmp = tempfile.mkdtemp()
A.DB = os.path.join(tmp, "s.db")
A.init()
A._setup_ops()
cl = A.app.test_client()
cl.get("/login")
with cl.session_transaction() as s:
    T = s["_csrf"]
cl.post("/login", data=dict(user="admin", pw="demo", _csrf=T))
with cl.session_transaction() as s:
    T = s["_csrf"]
rows = []
for k, sc in A.SCENARIOS.items():
    form = dict(sc["form"], _csrf=T, scenario=k)
    r = cl.post("/submit", data=form)
    rid = r.headers["Location"].rsplit("/", 1)[1]
    for _ in range(400):
        d = cl.get(f"/api/run/{rid}").get_json()
        if d["status"] != "Running":
            break
        time.sleep(0.5)
    rules = [f["rule"] + f["outcome"] for f in (d["result"] or {}).get("findings", [])]
    rows.append((k, sc["title"], d["status"], d["tier"], rules, sc.get("expect")))
    print(f"{k:14s} {d['status']:10s} {str(d['tier']):9s} {' '.join(rules)}", flush=True)
