import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
"""Build synthetic-but-realistic vendor data shaped by real public data.

Real inputs (data/real/raw): GLEIF Indian entities (name/state/legal-form stats),
RBI bank codes (banks.json), OFAC SDN list. Output entities are FICTIONAL: names are
recombined from real name tokens and rejected if they equal any real name; identifiers are
structurally valid (GSTIN check char computed) but belong to no real taxpayer is NOT guaranteed
by construction, so documents are always stamped SYNTHETIC SPECIMEN.
"""
import json, random, re, csv, collections, os
from validators import gstin_check_char, normalise_name, B36

R = random.Random(20261123)
RAW = "data/real/raw"
gl = json.load(open(f"{RAW}/gleif_in_all.json"))

# --- learn from real data ---------------------------------------------------
STATE_NAMES = {
    "27": "Maharashtra",
    "29": "Karnataka",
    "07": "Delhi",
    "33": "Tamil Nadu",
    "24": "Gujarat",
    "06": "Haryana",
    "09": "Uttar Pradesh",
    "36": "Telangana",
    "19": "West Bengal",
    "08": "Rajasthan",
}
state_ct, tokens, real_norm = collections.Counter(), collections.Counter(), set()
for r in gl:
    e = r["attributes"]["entity"]
    name = e["legalName"]["name"]
    rid = (e.get("registeredAs") or "").upper()
    real_norm.add(normalise_name(name))
    if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", rid):
        state_ct[rid[:2]] += 1
    for t in normalise_name(name).split():
        if len(t) > 3 and t.isalpha():
            tokens[t] += 1
state_w = [(s, c) for s, c in state_ct.most_common(10) if s in STATE_NAMES]
pool = [t for t, c in tokens.most_common(600) if c >= 3]
json.dump(
    {"gstin_state_share": dict(state_ct.most_common(12)), "token_pool_size": len(pool)},
    open("data/synth/learned_from_real.json", "w"),
    indent=1,
)

banks = json.load(open(f"{RAW}/banks.json"))
BANKS = {
    "HDFC": "HDFC Bank",
    "SBIN": "State Bank of India",
    "ICIC": "ICICI Bank",
    "UTIB": "Axis Bank",
    "KKBK": "Kotak Mahindra Bank",
    "PUNB": "Punjab National Bank",
    "YESB": "Yes Bank",
    "BARB": "Bank of Baroda",
}
BANK_IFSC = {c: banks[c]["ifsc"] for c in BANKS if c in banks}


def make_pan(name, kind):
    L = lambda: R.choice("ABCDEFGHJKLMNPRSTUVWXYZ")
    first = (name.split()[-1][0] if kind == "P" else normalise_name(name)[0]).upper()
    return L() + L() + L() + kind + first + "".join(R.choice("0123456789") for _ in range(4)) + L()


def make_gstin(state, pan, n=1):
    body = state + pan + str(n) + "Z"
    return body + gstin_check_char(body)


def make_cin(state_code2, year, klass):
    nic = "".join(R.choice("0123456789") for _ in range(5))
    return f"U{nic}{state_code2}{year}{klass}{R.randint(100000, 999999)}"


ST2 = {
    "27": "MH",
    "29": "KA",
    "07": "DL",
    "33": "TN",
    "24": "GJ",
    "06": "HR",
    "09": "UP",
    "36": "TG",
    "19": "WB",
    "08": "RJ",
}
CITY = {
    "27": "Pune",
    "29": "Bengaluru",
    "07": "New Delhi",
    "33": "Chennai",
    "24": "Ahmedabad",
    "06": "Gurugram",
    "09": "Noida",
    "36": "Hyderabad",
    "19": "Kolkata",
    "08": "Jaipur",
}
SECT = [
    "Logistics",
    "Packaging",
    "Industries",
    "Traders",
    "Solutions",
    "Enterprises",
    "Foods",
    "Engineering",
    "Services",
    "Textiles",
]


def fictional_entity(i):
    while True:
        words = [w.title() for w in R.sample(pool, 2)] + [R.choice(SECT)]
        name = " ".join(words)
        if normalise_name(name) not in real_norm:
            break
    kind = R.choices(["C", "F", "P"], [60, 25, 15])[0]
    st = R.choices([s for s, _ in state_w], [c for _, c in state_w])[0]
    legal = name + (" Private Limited" if kind == "C" else " LLP" if kind == "F" else "")
    if kind == "P":
        legal = f"{R.choice(['Amit','Priya','Rahul','Sunita','Vikram'])} {R.choice(['Sharma','Verma','Iyer','Patel','Nair'])}"
    pan = make_pan(legal, kind)
    bank = R.choice(list(BANK_IFSC))
    ent = dict(
        id=f"E{i:04d}",
        legal_name=legal,
        trade_name=name if kind != "P" else legal,
        country="IN",
        entity_type={"C": "Company", "F": "Firm/LLP", "P": "Individual"}[kind],
        pan=pan,
        gstin=make_gstin(st, pan),
        gst_status="Active",
        gst_composition=R.random() < 0.12,
        pan_operative=R.random() > 0.04,
        state=STATE_NAMES[st],
        city=CITY[st],
        state_code=st,
        cin=make_cin(ST2[st], R.randint(2005, 2023), "PTC") if kind == "C" else None,
        udyam=(
            f"UDYAM-{ST2[st]}-{R.randint(10,30):02d}-{R.randint(1000000,9999999)}"
            if R.random() < 0.4
            else None
        ),
        bank=BANKS[bank],
        ifsc=BANK_IFSC[bank],
        account="".join(R.choice("0123456789") for _ in range(R.choice([11, 12, 14]))),
        address=f"{R.randint(1,250)}, {R.choice(['MG Road','Industrial Area Phase 2','Link Road','Station Road'])}, {CITY[st]}, {STATE_NAMES[st]}",
    )
    return ent


registry = [fictional_entity(i) for i in range(1, 241)]
# registry status variation (ground truth the simulated GST/PAN lookups return)
for e in R.sample(registry, 6):
    e["gst_status"] = "Cancelled"
for e in R.sample(registry, 6):
    e["gst_status"] = "Suspended"
json.dump(registry, open("data/synth/registry.json", "w"), indent=1)

# --- sanctions index from the REAL OFAC SDN (+aliases) ----------------------
sdn = {}
for row in csv.reader(open(f"{RAW}/SDN.CSV", encoding="latin-1")):
    if len(row) > 3:
        sdn[row[0]] = dict(uid=row[0], name=row[1].strip(), type=row[2].strip(), program=row[3].strip())
for row in csv.reader(open(f"{RAW}/ALT.CSV", encoding="latin-1")):
    if len(row) > 3 and row[0] in sdn:
        sdn[row[0]].setdefault("aka", []).append(row[3].strip())
ents = [v for v in sdn.values() if v["type"] in ("-0-", "") or v["type"].lower() != "individual"]
json.dump(list(sdn.values()), open("data/synth/sanctions_index.json", "w"))
print("registry", len(registry), "| SDN records", len(sdn), "| non-individual", len(ents))
print("sample entity:", {k: registry[0][k] for k in ("legal_name", "gstin", "pan", "cin", "ifsc", "bank")})
