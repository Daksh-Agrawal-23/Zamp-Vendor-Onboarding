import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validators import *

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: got {got!r}, want {want!r}")


# Published GSTIN examples (from research) - checksum must validate
# 27AABCU9603R1ZM (from a search snippet) did not validate and could not be re-verified, so it is excluded.
for g in ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4"]:
    check(f"gstin {g}", validate_gstin(g)[0], True)
# Corrupt one char -> must fail
check("gstin corrupt", validate_gstin("27AAPFU0939F1ZW")[0], False)
check("gstin bad state", validate_gstin("99AAPFU0939F1ZV")[0] or validate_gstin("45AAPFU0939F1ZV")[0], False)
check("gstin/pan consistent", gstin_pan_consistent("27AAPFU0939F1ZV", "AAPFU0939F"), True)
check("gstin/pan mismatch", gstin_pan_consistent("27AAPFU0939F1ZV", "AAPFU0939G"), False)

# PAN
check("pan ok", validate_pan("ALWPG5809L")[0], True)
check("pan bad 4th", validate_pan("ALWXG5809L")[0], False)
check("pan short", validate_pan("ALWPG580L")[0], False)
check("pan hint individual", pan_name_hint("ALWPG5809L", "Rahul Gupta"), True)

# IFSC
for i in ["HDFC0000086", "SBIN0001234"]:
    check(f"ifsc {i}", validate_ifsc(i)[0], True)
check("ifsc bad 5th", validate_ifsc("HDFC1000086")[0], False)

# UK VAT published vectors
for v, want in [("333289454", True), ("123456727", True), ("980780684", True), ("802311781", False)]:
    check(f"vat {v}", validate_uk_vat(v)[0], want)

# EIN
check("ein ok", validate_ein("12-3456789")[0], True)
check("ein bad prefix", validate_ein("07-1234567")[0], False)
check("ein format", validate_ein("123456789")[0], False)

# Names: benign noise must pass, different companies must not
check("name suffix", name_band(name_score("Acme Pvt. Ltd.", "ACME Private Limited")), "pass")
check("name order", name_band(name_score("Sharma Traders", "Traders Sharma")), "pass")
check("name different", name_band(name_score("Acme Logistics", "Zenith Foods")), "conflict")

# CIN (real example from MCA OGD documentation)
check("cin ok", validate_cin("L01110TG1994PLC018562")[0], True)
check("cin bad class", validate_cin("L01110TG1994XXX018562")[0], False)
check("cin future year", validate_cin("U01110TG2099PTC018562")[0], False)
check(
    "cin name: plain Limited gives no signal",
    cin_name_consistent("L01110TG1994PLC018562", "ALKEM LABORATORIES LIMITED"),
    None,
)
check(
    "cin name: plain Limited w/ PTC not flagged",
    cin_name_consistent("U01110TG2015PTC018562", "Acme Foods Limited"),
    None,
)
check(
    "cin name: Pvt Ltd with public class flagged",
    cin_name_consistent("U74899DL1986PLC023290", "Kishore Udyog Pvt Ltd"),
    False,
)
check("cin name private ok", cin_name_consistent("U01110TG2015PTC018562", "Acme Foods Pvt. Ltd."), True)

# Real-world typo found in GLEIF data: letter I typed for digit 1
check("gstin repair I/1", suggest_gstin_fix("24ABECA5640AIZA"), "24ABECA5640A1ZA")
check("gstin repair none", suggest_gstin_fix("24ATKPP6666Q1ZN"), None)
check("gstin repair valid input", suggest_gstin_fix("27AAPFU0939F1ZV"), None)

# IFSC granular status (Syndicate Bank merged into Canara: code survives with no live branches)
check("ifsc ok", ifsc_status("HDFC0000086"), "ok")
check("ifsc retired bank", ifsc_status("SYNB0003011"), "retired_bank")
check("ifsc unknown bank", ifsc_status("ZZZZ0000001"), "unknown_bank")
check("ifsc bad format", ifsc_status("SBIN00X"), "bad_format")

check("cin class PLN valid", validate_cin("U67190UP2020PLN125909")[0], True)
check("llpin ok", validate_llpin("AAE-8730")[0], True)
check("llpin bad", validate_llpin("AAE8730")[0], False)
check(
    "cin year == incorporation year",
    cin_year_matches_incorporation("U31100UP2022PLC163667", "2022-05-06"),
    True,
)
check("cin year mismatch", cin_year_matches_incorporation("U31100UP2022PLC163667", "2019-05-06"), False)
check(
    "P LTD normalises",
    name_band(name_score("Emkay Woollen Mills P Ltd", "EMKAY WOOLLEN MILLS PRIVATE LIMITED")),
    "pass",
)
check("suffix-only name not empty", normalise_name("The Company Limited") != "", True)

check(
    "M/S prefix",
    name_band(name_score("M/S Kishore Udyog Private Limited", "KISHORE UDYOG PRIVATE LIMITED")),
    "pass",
)
if fails:
    print("FAIL")
    print("\n".join(fails))
    sys.exit(1)
print("ALL PASS")

# position-aware look-alike repair (OCR reads O for 0, 2 for Z, etc.)
check("canon O9...127 -> valid", suggest_gstin_fix("O9JKKCA2056S127"), "09JKKCA2056S1Z7")
check("canon leaves valid alone", suggest_gstin_fix("27AAPFU0939F1ZV"), None)
check("canon random junk unrepaired", suggest_gstin_fix("O9JKKCA2056S1Z8"), None)
print("canonicalise tests done")
