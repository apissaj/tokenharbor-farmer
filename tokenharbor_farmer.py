#!/usr/bin/env python3
"""
TokenHarbor Farmer — automated free-account registration for 9Router.

Clean, license-free alternative to the obfuscated ApiBor bot. Registers TokenHarbor
accounts using their Next.js Server Action, verifies email via your own Cloudflare
D1 temp-mail worker, then injects the credentials into 9Router as a `tokenbor`
provider.

Features:
  - Next.js Server Action signup (ACTION_ID reverse-engineered via Playwright)
  - Email verification through Cloudflare D1 (your own domains, no public tempmail)
  - Domain rotation across multiple catch-all domains
  - Automatic 9Router SQLite injection
  - Adaptive rate-limit handling (pauses on 403 / 429 / human-check)

Free models available per account:
  - mimo-v2.5:free
  - deepseek-v4-flash:free
  - qwen3.8-27b:free
  (th-orchestra requires balance > $0)

Requirements:
  - Python 3.11+
  - wrangler CLI authenticated (for D1 OTP lookup)
  - A Cloudflare D1 temp-mail worker (cloud-mail-db)
  - 9Router running with SQLite at the configured path

Environment variables:
  CLOUDFLARE_WORKER_DIR  Directory containing wrangler.toml for cloud-mail-db
  WRANGLER_BIN          Path to npx/wrangler binary
  NINEROUTER_DB         Path to 9Router data.sqlite
  TOKENHARBOR_DOMAINS   Comma-separated domains to rotate (optional override)

Usage:
  python tokenharbor_farmer.py batch 5 --inject
  python tokenharbor_farmer.py 1
  python tokenharbor_farmer.py test
  python tokenharbor_farmer.py 9router
"""
import os
import sys
import re
import json
import time
import uuid
import string
import random
import sqlite3
import subprocess
import requests
from datetime import datetime, timezone
from pathlib import Path

# ===== CONFIG =====
BASE = "https://tokenharbor.ai"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
ACTION_ID = "607ec2c1a962aa81ad67a2483c54b0cfadfda875b2"
ACTION_KEY = "kb59e6b88b9f36883e58e38e7e48870c6"
NEXT_ACTION = "607ec2c1a962aa81ad67a2483c54b0cfadfda875b2"
ROUTER = "[\"\",{\"children\":[\"login\",{\"children\":[\"__PAGE__\",{},null,null,0]},null,null,20]},null,null,20]"
TEST_MODEL = "mimo-v2.5:free"
FREE_MODELS = ["mimo-v2.5:free", "deepseek-v4-flash:free", "qwen3.8-27b:free"]

# Dirs (configurable via env)
WORKER_DIR = os.environ.get(
    "CLOUDFLARE_WORKER_DIR",
    r"C:\Users\TUF Gaming A15\cloud-mail-inspect\mail-worker",
)
NPX = os.environ.get(
    "WRANGLER_BIN",
    r"C:\Users\TUF Gaming A15\AppData\Local\hermes\node\npx.cmd",
)
NINE_ROUTER_DB = os.environ.get(
    "NINEROUTER_DB",
    str(Path.home() / "AppData" / "Roaming" / "9router" / "db" / "data.sqlite"),
)

# Domains (configurable via env: comma-separated)
_default_domains = [
    "ternakakun.biz.id",
    "infrasync.web.id",
    "schemacanvas.my.id",
    "hafizhmuzani.my.id",
]
_env_domains = os.environ.get("TOKENHARBOR_DOMAINS")
DOMAINS = [d.strip() for d in _env_domains.split(",") if d.strip()] if _env_domains else _default_domains

OTP_TIMEOUT = 120
OTP_POLL = 8

# Inter-account pacing (avoid Cloudflare Turnstile + IP rate-limit)
ACCOUNT_DELAY_BASE = 90       # seconds between successful accounts
ACCOUNT_DELAY_FAIL = 180      # seconds if the previous attempt failed
ACCOUNT_DELAY_RATELIMIT = 600  # seconds if 403/429/human-check detected

P = {}

# ===== HELPERS =====
def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{level}] {msg}")

def rand_pwd():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + '!Aa1'

_email_counter = {"n": 0}

def _next_email_num():
    _email_counter["n"] += 1
    return _email_counter["n"]

def gen_email(domain, index=None):
    """Generate a simple random email to avoid anti-abuse suspicion."""
    n = index if index is not None else _next_email_num()
    suffix = random.randint(10, 999)
    return f"useraaa{n:03d}{suffix}@{domain}"

# ===== SIGNUP BODY (Next.js Server Action) =====
def make_signup_body(email, pwd):
    fp = str(uuid.uuid4())
    # 6 dashes, not 4 — Next.js expects "------WebKitFormBoundary..."
    bd = "------WebKitFormBoundary" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    tz = "Asia/Jakarta"
    parts = []
    def af(n, v=""):
        # CRLF line endings required by Next.js multipart parser
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}')
    af("1_$ACTION_REF_1")
    af("1_$ACTION_1:0", json.dumps({"id": ACTION_ID, "bound": "$@1"}))
    af("1_$ACTION_1:1", '["$undefined"]')
    af("1_$ACTION_KEY", ACTION_KEY)
    af("1_device_fingerprint", fp)
    af("1_timezone", tz)
    af("1_next")
    af("1_email", email)
    af("1_password", pwd)
    af("1_invite_code")
    af("0", '["$undefined","$K1"]')
    body = "\r\n".join(parts) + f"\r\n--{bd}--\r\n"
    headers = {
        "Content-Type": f"multipart/form-data; boundary={bd}",
        "Accept": "text/x-component",
        "Next-Action": NEXT_ACTION,
        "Next-Router-State-Tree": ROUTER,
        "Origin": BASE,
        "Referer": f"{BASE}/login?mode=signup",
    }
    return body, headers

# ===== D1 OTP READER =====
def query_d1(sql):
    """Run SQL on cloud-mail D1, return list of rows."""
    cmd = [NPX, "wrangler", "d1", "execute", "cloud-mail-db", "--remote", "--command", sql, "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKER_DIR, timeout=120)
        if proc.returncode != 0:
            log(f"D1 query failed: {proc.stderr[:200]}", "WARN")
            return []
        data = json.loads(proc.stdout)
        return data[0].get("results", [])
    except Exception as e:
        log(f"D1 error: {e}", "WARN")
        return []

def wait_verification_link(email, max_wait=OTP_TIMEOUT):
    """Poll D1 for email to this address, return verification link from HTML content."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        rows = query_d1(f"SELECT email_id, content, subject FROM email WHERE to_email='{email}' ORDER BY create_time DESC LIMIT 1;")
        if rows:
            content = rows[0].get("content") or rows[0].get("message") or ""
            links = re.findall(r'(https://tokenharbor\.ai/verify-email\?[^\s"<>]+)', content)
            if links:
                log(f"Verification link found: {links[0][:60]}...")
                return links[0]
            subj = rows[0].get("subject", "")
            log(f"Email arrived (subject={subj}) but no verify link yet", "WARN")
        time.sleep(OTP_POLL)
    return None

# ===== 9ROUTER INJECT =====
def inject_to_9router(api_key, email, user_id=""):
    try:
        conn = sqlite3.connect(str(NINE_ROUTER_DB))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM providerConnections WHERE provider='tokenbor'")
        count = cur.fetchone()[0]
        conn_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        label = f"{email.split('@')[0][:6]} #{count + 1}"
        data = json.dumps({
            "defaultModel": "mimo-v2.5:free",
            "apiKey": api_key,
            "testStatus": "active",
            "providerSpecificData": {
                "prefix": "tokenbor",
                "apiType": "chat",
                "baseUrl": "https://tokenharbor.ai/v1",
                "nodeName": "tokenbor"
            }
        })
        cur.execute(
            "INSERT INTO providerConnections (id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt) VALUES (?, 'tokenbor', 'api_key', ?, ?, 0, 1, ?, ?, ?)",
            (conn_id, label, email, data, now, now)
        )
        conn.commit()
        conn.close()
        return True, label
    except Exception as e:
        return False, str(e)[:60]

def inject_show_9router():
    try:
        conn = sqlite3.connect(str(NINE_ROUTER_DB))
        cur = conn.cursor()
        cur.execute("SELECT id, name, email, isActive FROM providerConnections WHERE provider='tokenbor'")
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []

# ===== TEST MODEL =====
def test_model(api_key, model=TEST_MODEL):
    try:
        r = requests.post(f"{BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30, json={"model": model, "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 20})
        if r.status_code == 200:
            reply = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, f"200 OK - {reply[:30]}"
        else:
            return False, f"{r.status_code} - {r.text[:60]}"
    except Exception as e:
        return False, f"ERR - {str(e)[:50]}"

# ===== REGISTER ONE =====
def register_one(domain):
    """Register 1 account on TokenHarbor using cloud-mail D1 for verification."""
    email = gen_email(domain)
    pwd = rand_pwd()
    log(f"Email: {email}")

    s = requests.Session()
    s.headers.update({"User-Agent": UA})

    log("Loading login page...")
    for attempt in range(5):
        try:
            s.get(f"{BASE}/login", proxies=P or None, timeout=20)
            break
        except Exception:
            log(f"  Retry {attempt+1}/5...", "WARN")
            time.sleep(3)

    log("Submitting signup...")
    body, headers = make_signup_body(email, pwd)
    for attempt in range(5):
        try:
            r = s.post(f"{BASE}/login", data=body, headers=headers, proxies=P or None, timeout=25)
            break
        except Exception:
            log(f"  Retry {attempt+1}/5...", "WARN")
            time.sleep(3)
    else:
        return None, "proxy failed after 5 retries"

    resp_text = r.text
    if "signedIn" not in resp_text:
        errors = re.findall(r'"error":"([^"]+)"', resp_text)
        err = errors[0] if errors else f"HTTP {r.status_code} - {resp_text[:100]}"
        log(f"Signup FAILED: {err}", "ERROR")
        return None, err

    uid = re.findall(r'"userId":\s*"([^"]+)"', resp_text)
    log(f"Signup OK - userId: {uid[0] if uid else '?'}")

    log("Waiting for verification email via cloud-mail D1 (max 120s)...")
    verify_link = wait_verification_link(email)
    if verify_link:
        s.get(verify_link, timeout=15, allow_redirects=True)
        log("Email verified")
        verified = True
    else:
        log("Verification NOT received (timeout)", "WARN")
        verified = False

    log("Cleaning auto-created keys...")
    try:
        r2 = s.get(f"{BASE}/api/keys", headers={"Accept": "application/json"}, proxies=P or None, timeout=15)
        for k in r2.json().get("keys", []):
            s.delete(f"{BASE}/api/keys/{k['id']}", proxies=P or None, timeout=10)
    except Exception:
        pass

    log("Creating API key...")
    r3 = s.post(f"{BASE}/api/keys", json={"label": f"botbor-{random.randint(100,999)}"},
        headers={"Accept": "application/json", "Content-Type": "application/json"}, proxies=P or None, timeout=15)
    if r3.status_code != 201:
        log(f"Key create FAILED: {r3.status_code}", "ERROR")
        return None, f"key create failed {r3.status_code}"
    key = r3.json().get("plaintext")
    if not key:
        log("No plaintext in response", "ERROR")
        return None, "no plaintext"
    log(f"Key created: {key[:35]}...")

    log("Accepting free model consent...")
    rc = s.post(f"{BASE}/api/me/privacy", json={"free_models_enabled": True},
        headers={"Accept": "application/json", "Content-Type": "application/json"}, proxies=P or None, timeout=10)
    consent_ok = rc.status_code == 200 and '"ok":true' in rc.text
    log(f"Consent: {'Y' if consent_ok else 'N'} ({rc.status_code})")

    return {
        "email": email,
        "password": pwd,
        "userId": uid[0] if uid else "",
        "api_key": key,
        "verified": verified,
        "consent": consent_ok,
        "domain": domain,
    }, None

# ===== BATCH =====
def run_batch(n, inject=False):
    success = 0
    rate_limited = 0
    domain_idx = 0
    for i in range(n):
        domain = DOMAINS[domain_idx % len(DOMAINS)]
        domain_idx += 1

        print(f"\n  [{i+1}/{n}] " + "=" * 40)
        log(f"Domain: {domain}")
        rate_limited_this = False
        for attempt in range(5):
            try:
                account, err = register_one(domain)
                if account:
                    accounts = load_accounts()
                    accounts.append(account)
                    save_accounts(accounts)
                    save_key(account["api_key"])
                    success += 1

                    log("Testing free model...")
                    ok, info = test_free_model(account["api_key"])
                    log(f"Test {TEST_MODEL}: {'OK' if ok else 'FAIL'} {info}")
                    account["test_result"] = info

                    v = "Y" if account.get("verified") else "N"
                    c = "Y" if account.get("consent") else "N"
                    t = "Y" if ok else "N"
                    print(f"  RESULT: {account['email']} [verify:{v}] [consent:{c}] [model:{t}]")

                    if inject:
                        injected, msg = inject_to_9router(account["api_key"], account["email"], account.get("userId", ""))
                        log(f"{'Injected' if injected else 'Inject failed'}: {msg}")

                    save_accounts(accounts)
                    break
                else:
                    short = (err or "")[:80]
                    log(f"Attempt {attempt+1}: {short}", "ERROR")
                    if any(s in short for s in ["human check", "HTTP 429", "HTTP 403", "balance_zero"]):
                        rate_limited_this = True
                        rate_limited += 1
                        break
            except Exception as e:
                log(f"Attempt {attempt+1}: {str(e)[:30]}", "ERROR")
            time.sleep(random.randint(3, 7))

        if i < n - 1:
            if rate_limited_this:
                log(f"Rate-limit detected. Sleeping {ACCOUNT_DELAY_RATELIMIT}s before next account...", "WARN")
                if ACCOUNT_DELAY_RATELIMIT > 60:
                    log("Stopping batch to protect IP from further throttling.", "WARN")
                    break
                time.sleep(ACCOUNT_DELAY_RATELIMIT)
            else:
                just_succeeded = success > 0 and (
                    len(load_accounts()) and load_accounts()[-1].get("domain") == domain
                )
                wait = ACCOUNT_DELAY_BASE if just_succeeded else ACCOUNT_DELAY_FAIL
                jitter = random.randint(-10, 15)
                wait = max(30, wait + jitter)
                log(f"Waiting {wait}s before next account...")
                time.sleep(wait)
    log(f"Run summary: {success} ok, {rate_limited} rate-limited, {n} requested", "INFO")
    return success

# ===== STORAGE =====
ACCOUNT_FILE = Path(__file__).parent / "accounts.json"
APIKEY_FILE = Path(__file__).parent / "apikeys.txt"

def load_accounts():
    if ACCOUNT_FILE.exists():
        with open(ACCOUNT_FILE) as f:
            return json.load(f)
    return []

def save_accounts(data):
    with open(ACCOUNT_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_keys():
    if APIKEY_FILE.exists():
        with open(APIKEY_FILE) as f:
            return [l.strip() for l in f if l.strip()]
    return []

def save_key(key):
    with open(APIKEY_FILE, "a") as f:
        f.write(f"{key}\n")

# ===== COMMANDS =====
def cmd_test_all():
    """Test all keys x all free models. Display results as a table."""
    keys = load_keys()
    if not keys:
        print("\n  Tidak ada key di apikeys.txt")
        return
    col_w = 18
    key_w = 15
    header = f"  {'Key':<{key_w}}" + "".join(f"{m:<{col_w}}" for m in FREE_MODELS)
    print(f"\n  Test semua key x semua model gratis:")
    print(f"  {'—'*len(header)}")
    print(header)
    print(f"  {'—'*len(header)}")
    totals = {m: 0 for m in FREE_MODELS}
    for i, k in enumerate(keys):
        row = f"  {k[10:25]:<{key_w}}"
        for m in FREE_MODELS:
            valid, info = test_model(k, m)
            tag = "OK" if valid else "FAIL"
            row += f"{tag:<{col_w}}"
            if valid:
                totals[m] += 1
        print(row)
    print(f"  {'—'*len(header)}")
    total_row = f"  {'TOTAL':<{key_w}}"
    for m in FREE_MODELS:
        total_row += f"{totals[m]}/{len(keys):<{col_w}}"
    print(total_row)
    print()

def cmd_monitor():
    """Health check pool tokenbor: jumlah key, model hidup, total jalur API."""
    rows = inject_show_9router()
    keys = load_keys()
    total_paths = 0
    print(f"\n  ╔══════════════════════════════════════════════════╗")
    print(f"  ║  TOKENHARBOR POOL — Health Check                ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    print(f"  ║  Akun di 9Router : {len(rows):>3}                          ║")
    print(f"  ║  Key di file     : {len(keys):>3}                          ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    # List each 9Router entry
    for r in rows:
        name, email, active = r[1], r[2], r[3]
        status = "🟢 aktif" if active else "🔴 mati"
        print(f"  ║  {status}  {name:<18} {email[:25]:<25} ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    # Model health (test first key only for speed)
    print(f"  ║  Model Health (test key pertama)                ║")
    if keys:
        for m in FREE_MODELS:
            valid, info = test_model(keys[0], m)
            tag = "🟢 hidup" if valid else "🔴 mati"
            paths = len(rows) if valid else 0
            total_paths += paths
            short = m.replace(":free", "")
            print(f"  ║    {tag}  {short:<25} {paths:>2} jalur   ║")
    else:
        for m in FREE_MODELS:
            print(f"  ║    ⚪ tanpa key   {m:<25}      ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    print(f"  ║  Total jalur API gratis : {total_paths:>3}                ║")
    print(f"  ╚══════════════════════════════════════════════════╝")
    # Warnings
    if len(rows) != len(keys):
        print(f"\n  ⚠️  9Router punya {len(rows)} entry tapi apikeys.txt punya {len(keys)} key.")
        print(f"      Key baru belum ter-inject, atau ada key tanpa entry.")
    print()

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("\nUsage: python tokenharbor_farmer.py [batch N [--inject] | test | monitor]")
    elif args[0] == "batch":
        n = int(args[1]) if len(args) > 1 else 5
        inject = "--inject" in args
        ok = run_batch(n, inject=inject)
        print(f"\n  Done: {ok}/{n}")
    elif args[0] == "test":
        cmd_test_all()
    elif args[0] == "monitor":
        cmd_monitor()
    else:
        print(f"Unknown command: {args[0]}")
        print(__doc__)

if __name__ == "__main__":
    main()
