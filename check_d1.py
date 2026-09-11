"""check_d1.py — quick sanity check that wrangler can query cloud-mail D1.
Run from anywhere; uses the same NPX path + WORKER_DIR as tokenharbor_farmer.py.
"""
import subprocess, json, sys

NPX = r"C:\Users\TUF Gaming A15\AppData\Local\hermes\node\npx.cmd"
WORKER_DIR = r"C:\Users\TUF Gaming A15\cloud-mail-inspect\mail-worker"

cmd = [NPX, "wrangler", "d1", "execute", "cloud-mail-db", "--remote", "--command",
       "SELECT COUNT(*) AS n FROM email;", "--json"]
try:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKER_DIR, timeout=120)
except Exception as e:
    print("EXEC ERROR:", e)
    sys.exit(1)

print("returncode:", proc.returncode)
if proc.returncode != 0:
    print("STDERR:", proc.stderr[:500])
    sys.exit(1)

try:
    data = json.loads(proc.stdout)
    rows = data[0].get("results", [])
    print("rows:", rows)
except Exception as e:
    print("PARSE ERROR:", e)
    print("STDOUT:", proc.stdout[:500])
