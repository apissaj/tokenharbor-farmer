"""
Continuous TokenHarbor farmer — auto-chains batches with safety aborts.

- Batch size: 10 accounts (Japanese display names, guaranteed-unique emails)
- 15-minute cooldown between batches
- Before each batch: proxy health check (abort if dead)
- After each batch: re-normalize 9Router priorities (oldest = highest)
- Abort conditions: farmer crash, proxy dead, or a batch with 0 new accounts
  (0 ok almost always means proxy quota exhausted or signup blocked)
- Per-batch logs in logs/
"""
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
FARMER = HERE / "tokenharbor_farmer_proxy.py"
PRIORITY = HERE / "normalize_priority.py"
LOGDIR = HERE / "logs"
LOGDIR.mkdir(exist_ok=True)

DB = r"C:\Users\TUF Gaming A15\AppData\Roaming\9router\db\data.sqlite"
TARGET = "openai-compatible-chat-07ede055-d26a-4690-9e3b-b1930b247502"
PROXY_URL = "http://bpuser-Jb9ByL9q:yvaBlkrckX2izmSb2Blc_country-US,AU,JP,KR,SG,TR,SA,PT,PS,QA,PH,PL@residential.bpproxy.at:1000"

BATCH_SIZE = 10
MAX_BATCHES = 32  # run-6: pool 686 -> ~1000
COOLDOWN = 0  # no cooldown


def ts():
    return datetime.now().strftime("%H:%M:%S")


def th_count():
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        n = conn.execute(
            "SELECT COUNT(*) FROM providerConnections WHERE provider=?", (TARGET,)
        ).fetchone()[0]
        conn.close()
        return n
    except Exception as e:
        return f"ERR:{e}"


def proxy_alive():
    try:
        r = requests.get(
            "https://api.ipify.org?format=json",
            proxies={"http": PROXY_URL, "https": PROXY_URL},
            timeout=25,
        )
        return (r.status_code == 200), r.text.strip()
    except Exception as e:
        return False, str(e)[:100]


def normalize_priority():
    try:
        r = subprocess.run(
            [sys.executable, str(PRIORITY)],
            cwd=str(HERE), capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout or r.stderr or "").strip()
        print(f"[{ts()}] {out}", flush=True)
    except Exception as e:
        print(f"[{ts()}] [WARN] priority normalize failed: {e}", flush=True)


def run_batch(n):
    logf = LOGDIR / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    env = {**os.environ, "PYTHONUTF8": "1"}
    buf = []
    with open(logf, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen(
            [sys.executable, str(FARMER), "batch", str(n), "--inject"],
            cwd=str(HERE), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lf.write(line)
            lf.flush()
            buf.append(line)
        proc.wait()
    m = re.search(r"Run summary: (\d+) ok", "".join(buf))
    return proc.returncode, (int(m.group(1)) if m else 0), logf


def main():
    # NOTE: pre-inject block removed (2026-09-04) — it re-added deleted unavailable
    # accounts with email=missing@tokenharbor.ai. New accounts are injected by
    # tokenharbor_farmer_proxy.py --inject directly.

    print(
        f"[{ts()}] === CONTINUOUS MODE | start TH={th_count()} | "
        f"batch={BATCH_SIZE} | max={MAX_BATCHES} | cooldown={COOLDOWN}s ===",
        flush=True,
    )
    for b in range(1, MAX_BATCHES + 1):
        alive, info = proxy_alive()
        if not alive:
            print(f"[{ts()}] >>> ABORT: proxy dead before batch {b} ({info})", flush=True)
            return
        print(
            f"\n########## BATCH {b}/{MAX_BATCHES} | proxy {info} | TH={th_count()} ##########",
            flush=True,
        )
        rc, ok, logf = run_batch(BATCH_SIZE)
        if rc != 0:
            print(f"[{ts()}] >>> ABORT: farmer exited rc={rc} (log: {logf})", flush=True)
            return
        normalize_priority()
        print(
            f"[{ts()}] BATCH {b} DONE: {ok}/{BATCH_SIZE} ok | TH={th_count()} | log={logf}",
            flush=True,
        )
        if ok == 0:
            print(
                f"[{ts()}] >>> ABORT: 0 akun sukses (quota proxy habis / signup blocked). Stop chain.",
                flush=True,
            )
            return
        if b < MAX_BATCHES:
            print(f"[{ts()}] Cooldown {COOLDOWN}s sebelum batch berikutnya ...", flush=True)
            time.sleep(COOLDOWN)

    print(f"\n[{ts()}] === CONTINUOUS MODE FINISHED | final TH={th_count()} ===", flush=True)


if __name__ == "__main__":
    main()
