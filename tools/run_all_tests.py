"""Run every test script and print one line each. Usage (from the project root): python tools/run_all_tests.py"""

import glob, os, subprocess, sys

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
env = dict(os.environ, PYTHONPATH=root, STAGE_DELAY="0")
bad = 0
for t in sorted(glob.glob(os.path.join(root, "tests", "test_*.py"))):
    r = subprocess.run([sys.executable, t], cwd=root, env=env, capture_output=True, text=True)
    print(("PASS " if r.returncode == 0 else "FAIL ") + os.path.basename(t))
    if r.returncode:
        bad += 1
        print(r.stdout[-800:], r.stderr[-800:])
sys.exit(1 if bad else 0)
