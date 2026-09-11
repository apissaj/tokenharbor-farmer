"""TokenHarbor Run-7: 100 akun lanjutan (10 batch x 10).
Kloning continuous_batches.py dengan MAX_BATCHES=10. Cooldown 0, abort sama.
Pakai state run-6 (TH pool=1006) sebagai basis.
"""
import os, re, sqlite3, subprocess, sys, time
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
MAX_BATCHES = 10  # 10 x 10 = 100 akun
START_BATCH = 4   # resume run-7 dari batch 4 (batch 1-3 = 30 akun sudah selesai)
COOLDOWN = 0

def ts():
    return datetime.now().strftime("%H:%M:%S")

def th_count():
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        n = conn.execute("SELECT COUNT(*) FROM providerConnections WHERE provider=?", (TARGET,)).fetchone()[0]
        conn.close()
        return n
    except Exception as e:
        return f"ERR:{e}"

def proxy_alive(retries=3):
    endpoints = [
        "https://api.ipify.org?format=json",
        "https://ifconfig.me/ip",
        "http://ip-api.com/json",
    ]
    for attempt in range(1, retries + 1):
        for url in endpoints:
            try:
                r = requests.get(url, proxies={"http": PROXY_URL, "https": PROXY_URL}, timeout=30)
                if r.status_code == 200:
                    return True, r.text.strip()[:60]
            except Exception:
                pass
        if attempt < retries:
            time.sleep(4)
    return False, "all endpoints timed out"

def normalize_priority():
    try:
        r = subprocess.run([sys.executable, str(PRIORITY)], cwd=str(HERE),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout or r.stderr or "").strip()
        print(f"[{ts()}] {out}", flush=True)
    except Exception as e:
        print(f"[{ts()}] [WARN] priority normalize failed: {e}", flush=True)

def run_batch(n):
    logf = LOGDIR / f"run7_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    env = {**os.environ, "PYTHONUTF8": "1"}
    buf = []
    with open(logf, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen([sys.executable, str(FARMER), "batch", str(n), "--inject"],
                                cwd=str(HERE), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)
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
    print(f"[{ts()}] === RUN-7 RESUME | start TH={th_count()} | target=+70 akun ({MAX_BATCHES-START_BATCH+1} batch tersisa) ===", flush=True)
    start_count = th_count() if isinstance(th_count(), int) else 0
    for b in range(START_BATCH, MAX_BATCHES + 1):
        alive, info = proxy_alive()
        if not alive:
            print(f"[{ts()}] >>> ABORT: proxy dead sebelum batch {b} ({info})", flush=True)
            return
        print(f"\n########## RUN-7 BATCH {b}/{MAX_BATCHES} | proxy {info} | TH={th_count()} ##########", flush=True)
        rc, ok, logf = run_batch(BATCH_SIZE)
        if rc != 0:
            print(f"[{ts()}] >>> ABORT: farmer exit rc={rc} (log: {logf})", flush=True)
            return
        normalize_priority()
        print(f"[{ts()}] BATCH {b} DONE: {ok}/{BATCH_SIZE} ok | TH={th_count()} | log={logf}", flush=True)
        if ok == 0:
            print(f"[{ts()}] >>> ABORT: 0 akun sukses (proxy quota / signup blocked)", flush=True)
            return
        if b < MAX_BATCHES:
            time.sleep(COOLDOWN)
    final = th_count()
    delta = (final - start_count) if isinstance(final, int) and isinstance(start_count, int) else "?"
    print(f"\n[{ts()}] === RUN-7 FINISHED | start={start_count} final={final} delta={delta} ===", flush=True)

if __name__ == "__main__":
    main()
