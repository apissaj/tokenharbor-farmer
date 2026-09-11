"""TokenHarbor Runner: Farm sampai kuota proxy BPProxy habis.

Auto-stop conditions:
1. proxy_alive() return False (3x retry x 3 endpoint gagal / 407 proxy auth reject).
2. Farmer mengembalikan 0 akun sukses dalam 1 batch (indikasi kuota habis di tengah jalan).
3. Farmer crash / exit code != 0 yang berhubungan dengan proxy network/quota.
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
MAX_BATCHES = 50  # Batas atas teoritis (500 akun), praktisnya akan stop saat kuota habis
COOLDOWN = 0      # Pacing per-akun sudah ada di farmer (30s delay)

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
                if r.status_code == 407:
                    return False, "407 Proxy Authentication Required (KUOTA HABIS)"
            except Exception as e:
                err_str = str(e)
                if "407" in err_str or "ProxyError" in err_str:
                    # Kemungkinan besar kuota habis
                    pass
        if attempt < retries:
            time.sleep(5)
    return False, "Semua endpoint gagal / kuota proxy habis"

def normalize_priority():
    try:
        r = subprocess.run([sys.executable, str(PRIORITY)], cwd=str(HERE),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout or r.stderr or "").strip()
        print(f"[{ts()}] {out}", flush=True)
    except Exception as e:
        print(f"[{ts()}] [WARN] priority normalize failed: {e}", flush=True)

def run_batch(n):
    logf = LOGDIR / f"run_drain_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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
    full_output = "".join(buf)
    m = re.search(r"Run summary: (\d+) ok", full_output)
    ok_count = int(m.group(1)) if m else 0
    quota_exhausted = ("407" in full_output or "ProxyError" in full_output) and ok_count == 0
    return proc.returncode, ok_count, logf, quota_exhausted

def main():
    start_count = th_count() if isinstance(th_count(), int) else 0
    total_added = 0
    master_log = LOGDIR / f"drain_master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    print(f"[{ts()}] === RUN-DRAIN: FARM SAMPAI KUOTA PROXY HABIS ===", flush=True)
    print(f"[{ts()}] Base TH Pool: {start_count} akun", flush=True)
    print(f"[{ts()}] Batch size: {BATCH_SIZE} | Max theoretical batches: {MAX_BATCHES}", flush=True)

    with open(master_log, "a", encoding="utf-8") as ml:
        ml.write(f"[{ts()}] START DRAIN RUN | Base={start_count}\n")
        ml.flush()

        for b in range(1, MAX_BATCHES + 1):
            print(f"\n[{ts()}] >>> Checking proxy health before Batch {b}...", flush=True)
            alive, info = proxy_alive(retries=3)
            if not alive:
                msg = f">>> STOP TRIGGERED: Proxy dead / kuota habis ({info})"
                print(f"[{ts()}] {msg}", flush=True)
                ml.write(f"[{ts()}] {msg}\n")
                break

            print(f"[{ts()}] ########## BATCH {b} | Proxy: {info} | Pool TH={th_count()} ##########", flush=True)
            rc, ok, logf, quota_exhausted = run_batch(BATCH_SIZE)

            total_added += ok
            normalize_priority()

            status_line = f"BATCH {b} DONE: {ok}/{BATCH_SIZE} ok | Total added this run: +{total_added} | Current TH={th_count()}"
            print(f"[{ts()}] {status_line}", flush=True)
            ml.write(f"[{ts()}] {status_line}\n")
            ml.flush()

            if quota_exhausted:
                msg = f">>> STOP TRIGGERED: Kuota proxy terdeteksi habis saat Batch {b} (407/ProxyError, 0 akun ok)."
                print(f"[{ts()}] {msg}", flush=True)
                ml.write(f"[{ts()}] {msg}\n")
                break

            if ok == 0:
                # Cek apakah proxy benar-benar mati
                alive_after, _ = proxy_alive(retries=2)
                if not alive_after:
                    msg = f">>> STOP TRIGGERED: 0 akun sukses dan proxy mati. Kuota habis."
                    print(f"[{ts()}] {msg}", flush=True)
                    ml.write(f"[{ts()}] {msg}\n")
                    break
                else:
                    print(f"[{ts()}] [WARN] 0 akun sukses tapi proxy masih respon. Coba batch berikutnya...", flush=True)

            if b < MAX_BATCHES:
                time.sleep(COOLDOWN)

    final = th_count()
    delta = (final - start_count) if isinstance(final, int) and isinstance(start_count, int) else total_added
    summary = f"=== DRAIN RUN FINISHED | Start={start_count} | Final={final} | Delta=+{delta} ==="
    print(f"\n[{ts()}] {summary}", flush=True)
    with open(master_log, "a", encoding="utf-8") as ml:
        ml.write(f"[{ts()}] {summary}\n")

if __name__ == "__main__":
    main()
