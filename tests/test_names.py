import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validators import name_score, name_band

PAIRS = [  # (a, b, expected band) - real-world Indian variants and look-alikes
    ("Ramesh Kumar Sharma", "R K Sharma", "pass"),
    ("Mohd Ali Traders", "Mohammed Ali Traders", "pass"),
    ("Gupta Bros", "Gupta Brothers", "pass"),
    ("Rakesh Gupta", "Rakesh Kumar Gupta", "pass"),
    ("Shri Ramesh Chand Gupta", "Ramesh Chand Gupta", "pass"),
    ("Patel Engg Works", "Patel Engineering Works Pvt Ltd", "pass"),
    ("M/s Sharma Traders (Prop. Ramesh Sharma)", "Sharma Traders", "pass"),
    ("Acme Pvt Ltd", "ACME PRIVATE LIMITED", "pass"),
    ("Sharma Traders", "Traders Sharma", "pass"),
    ("Ramesh Traders", "Rakesh Traders", "conflict"),
    ("Anil Kumar Singh", "Anil Kumar Sinha", "conflict"),
    ("Acme Logistics", "Zenith Foods", "conflict"),
    ("Ramesh Gupta", "Suresh Gupta", "conflict"),
    ("Rakesh Sharma", "Rakesh Verma", "conflict"),
    ("Gupta Traders", "Gupta", "review"),
    ("TCS Ltd", "Tata Consultancy Services Ltd", "review"),
    ("Sri Lakshmi Textiles", "Lakshmi Textiles", "pass"),
    ("Jain Industries", "Jain Inds", "pass"),
    ("Lakshmi Traders", "Laxmi Traders", "pass"),
    ("Krupa Enterprises", "Kripa Enterprises", "pass"),
    ("Pooja Stores", "Puja Stores", "pass"),
    ("Aarti Industries", "Arti Industries", "pass"),
    ("Rafiq Traders", "Rafique Traders", "pass"),
    ("Leyland Motors", "Layland Motors", "pass"),
    ("Sairam Agencies", "Sai Ram Agencies", "pass"),
    ("Mahalakshmi Silks", "Maha Lakshmi Silks", "pass"),
    ("Cipla Labs", "Cipla Laboratories Ltd", "pass"),
    ("Zenith Foods (formerly Acme Foods) Pvt Ltd", "Zenith Foods Private Limited", "pass"),
    ("BHEL", "Bharat Heavy Electricals Limited", "review"),
    ("HUL", "Hindustan Unilever Limited", "review"),
    ("R Sharma", "Ramesh Sharma", "review"),
    ("Sairam Agencies", "Sri Ganesh Agencies", "conflict"),
    ("Rahul Traders", "Rahil Traders", "conflict"),
    ("Pooja Stores", "Pooja Medical Stores", "review"),
]
bad = 0
for a, b, exp in PAIRS:
    got = name_band(name_score(a, b))
    ok = got == exp or (exp == "review" and got in ("review", "conflict") and False)
    if not ok:
        bad += 1
        print("FAIL", a, "|", b, "| expected", exp, "got", got, name_score(a, b))
print("NAME TESTS", "PASS" if not bad else f"{bad} FAILED")
sys.exit(1 if bad else 0)
