import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pandas as pd, re, json, collections
from validators import (
    validate_cin,
    parse_cin,
    normalise_name,
    normalise_suffix_text,
    cin_name_consistent,
    cin_state_matches,
)

D = "data/real/mca/"
df = pd.concat(
    [
        pd.read_csv(D + "up_or_mh_A.csv", dtype=str, keep_default_na=False),
        pd.read_csv(D + "up_or_mh_B.csv", dtype=str, keep_default_na=False),
    ],
    ignore_index=True,
)
df = df.drop_duplicates("CIN")
out = {"rows": len(df)}
df["is_llp"] = df.CIN.str.match(r"^[A-Z]{3}-\d{4}$")
df["is_cin"] = df.CIN.str.match(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")
out["kinds"] = {
    "company_cin": int(df.is_cin.sum()),
    "llpin": int(df.is_llp.sum()),
    "other": int((~df.is_cin & ~df.is_llp).sum()),
}
out["status"] = df.CompanyStatus.value_counts().head(10).to_dict()
c = df[df.is_cin]
v = c.CIN.map(lambda x: validate_cin(x)[0])
out["cin_valid_rate"] = round(float(v.mean()), 5)
out["cin_invalid_examples"] = c.CIN[~v].head(5).tolist()
p = c.CIN.map(parse_cin)
c = c.assign(
    klass=p.map(lambda x: x["klass"] if x else None),
    year=p.map(lambda x: x["year"] if x else None),
    stc=p.map(lambda x: x["state"] if x else None),
)
out["cin_class_counts"] = c.klass.value_counts().head(8).to_dict()
out["cin_roc_state_codes"] = c.stc.value_counts().head(12).to_dict()
# CIN year vs registration date year
reg = pd.to_datetime(c.CompanyRegistrationdate_date, errors="coerce")
ok = reg.notna()
out["cin_year_eq_reg_year"] = round(float((reg[ok].dt.year == c.year[ok]).mean()), 4)
# class vs name consistency on real data
cons = [cin_name_consistent(a, b) for a, b in zip(c.CIN, c.CompanyName)]
known = [x for x in cons if x is not None]
out["cin_class_vs_name_match"] = round(sum(known) / len(known), 4)
out["cin_class_vs_name_n"] = len(known)
# CIN ROC-state vs the state in the address field
st = c.CompanyStateCode.str.upper().str.replace(" ", "")
out["state_field_values"] = c.CompanyStateCode.str.lower().value_counts().head(6).to_dict()
# legal-suffix vocabulary in real names
suf = collections.Counter()
for n in df.CompanyName.sample(200000, random_state=1):
    toks = re.sub(r"[^A-Z ]", " ", n.upper()).split()
    if toks:
        suf[toks[-1]] += 1
    if len(toks) > 1:
        suf[" ".join(toks[-2:])] += 1
out["top_name_endings"] = dict(suf.most_common(25))
# status mix by kind, and Active-only
out["strike_off_share"] = round(float((df.CompanyStatus != "Active").mean()), 4)
# address concentration (shell-company signal): companies per normalised registered address
addr = df.Registered_Office_Address.str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
vc = addr[addr.str.len() > 15].value_counts()
out["addresses_with_>=50_entities"] = int((vc >= 50).sum())
out["addresses_with_>=10"] = int((vc >= 10).sum())
out["top_address_counts"] = vc.head(5).tolist()
out["share_of_entities_at_10plus_address"] = round(float(vc[vc >= 10].sum() / vc.sum()), 4)
# exact normalised-name collisions between DISTINCT entities
nn = df.CompanyName.map(normalise_name)
nc = nn.value_counts()
out["distinct_entities_sharing_normalised_name_pct"] = round(float(nc[nc > 1].sum() / len(nn)), 4)
out["max_same_name"] = int(nc.iloc[0])
out["same_name_top"] = nc.head(5).to_dict()
df.to_pickle("/tmp/mca.pkl")
json.dump(out, open("data/real/mca_profile.json", "w"), indent=1)
print(json.dumps(out, indent=1))
