#!/usr/bin/env python3
"""
TokenHarbor signup via Playwright stealth — no Capsolver, no paid API.

Proven approach: Playwright stealth → Turnstile invisible auto-solve →
Server Action submit → D1 email verify → browser fetch for API key →
9Router inject.  Works on fresh IP (mobile tethering recommended).

Env vars (optional overrides):
  CLOUDFLARE_WORKER_DIR, WRANGLER_BIN, NINEROUTER_DB, TOKENHARBOR_DOMAINS
"""
import os, sys, re, json, time, uuid, string, random, subprocess, sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# ===== CONFIG =====
BASE = "https://tokenharbor.ai"
WORKER_DIR = os.environ.get("CLOUDFLARE_WORKER_DIR", r"C:\Users\TUF Gaming A15\cloud-mail-inspect\mail-worker")
NPX = os.environ.get("WRANGLER_BIN", r"C:\Users\TUF Gaming A15\AppData\Local\hermes\node\npx.cmd")
NINE_DB = os.environ.get("NINEROUTER_DB", str(Path.home() / "AppData" / "Roaming" / "9router" / "db" / "data.sqlite"))
_domains_env = os.environ.get("TOKENHARBOR_DOMAINS")
DOMAINS = [d.strip() for d in _domains_env.split(",") if d.strip()] if _domains_env else [
    "ternakakun.biz.id", "infrasync.web.id", "schemacanvas.my.id", "hafizhmuzani.my.id"
]
FREE_MODELS = ["mimo-v2.5:free", "deepseek-v4-flash:free", "qwen3.8-27b:free"]
TEST_MODEL = "mimo-v2.5:free"
OTP_TIMEOUT, OTP_POLL = 120, 8
ACCOUNT_DELAY = 90  # seconds between accounts
RATELIMIT_DELAY = 600

_email_counter = {"n": 0}
def gen_email(domain):
    n = _email_counter["n"]; _email_counter["n"] += 1
    return f"useraaa{n:03d}{random.randint(10,999)}@{domain}"
def rand_pwd():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + '!Aa1'

def log(msg, level="INFO"):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] [{level}] {msg}")

# ===== D1 OTP =====
def poll_verify_link(email):
    deadline = time.time() + OTP_TIMEOUT
    while time.time() < deadline:
        try:
            cmd = [NPX, "wrangler", "d1", "execute", "cloud-mail-db", "--remote",
                   "--command", f"SELECT content FROM email WHERE to_email='{email}' ORDER BY create_time DESC LIMIT 1;", "--json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=WORKER_DIR, timeout=120)
            rows = json.loads(proc.stdout)[0].get("results", [])
            if rows:
                content = rows[0].get("content") or ""
                links = re.findall(r'(https://tokenharbor\.ai/verify-email\?[^\s"<>]+)', content)
                if links:
                    return links[0]
        except Exception:
            pass
        time.sleep(OTP_POLL)
    return None

# ===== BROWSER SIGNUP =====
def browser_signup_one(domain, user_id):
    email = gen_email(domain)
    pwd = rand_pwd()
    print(f"\n  [{user_id}] Email: {email}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        # Capture Next-Action requests for debugging
        captured = {"next_action": None, "response_text": None}
        def on_request(req):
            na = req.headers.get("next-action")
            if na: captured["next_action"] = na
        page.on("request", on_request)

        # 1. Navigate
        log(f"[{user_id}] Navigating to signup page...")
        try:
            page.goto(f"{BASE}/login?mode=signup", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log(f"[{user_id}] goto error: {e}", "WARN")
        page.wait_for_timeout(5000)

        # 2. Click Sign up tab
        try:
            page.get_by_role("button", name="Sign up").first.click(timeout=4000)
            log(f"[{user_id}] Clicked Sign up tab")
        except Exception:
            log(f"[{user_id}] Sign up tab not found, continuing")
        page.wait_for_timeout(2000)

        # 3. Wait for email input to appear (Turnstile solves in background)
        log(f"[{user_id}] Waiting for email form (Turnstile auto-solve)...")
        email_locator = None
        for attempt in range(40):  # up to 40s
            page.wait_for_timeout(1000)
            # Try multiple selectors
            for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail"]',
                        'input[placeholder*="MAIL"]']:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    email_locator = loc.first
                    break
            if not email_locator:
                try:
                    loc = page.get_by_label("EMAIL")
                    if loc.count() > 0:
                        email_locator = loc.first
                except Exception:
                    pass
            if not email_locator:
                try:
                    loc = page.get_by_label("Email")
                    if loc.count() > 0:
                        email_locator = loc.first
                except Exception:
                    pass
            if email_locator:
                break
        if not email_locator:
            # Dump page state for debug
            body = page.evaluate("() => document.body.innerText.slice(0,500)")
            log(f"[{user_id}] FORM NOT FOUND after 40s. Body: {body[:200]}", "ERROR")
            browser.close()
            return None, "form_not_found"

        log(f"[{user_id}] Email form appeared after ~{attempt+1}s")

        # 4. Fill form
        email_locator.fill(email)
        page.wait_for_timeout(300)
        # Password field
        try:
            page.locator('input[type="password"]').first.fill(pwd)
        except Exception:
            try:
                page.get_by_label("PASSWORD").first.fill(pwd)
            except Exception:
                page.get_by_label("Password").first.fill(pwd)
        page.wait_for_timeout(500)
        log(f"[{user_id}] Form filled")

        # 5. Click Create account
        try:
            page.get_by_role("button", name="Create account").first.click(timeout=6000)
            log(f"[{user_id}] Clicked Create account")
        except Exception:
            try:
                page.locator('button[type="submit"]').first.click(timeout=4000)
                log(f"[{user_id}] Clicked submit button")
            except Exception as e:
                log(f"[{user_id}] Submit err: {e}", "ERROR")
                browser.close()
                return None, "submit_failed"

        page.wait_for_timeout(5000)

        # 6. Check result
        body = page.evaluate("() => document.body.innerText.slice(0,600)")
        if "human check" in body.lower() or "429" in body:
            log(f"[{user_id}] Still human check or rate-limited", "ERROR")
            browser.close()
            return None, "human_check"
        log(f"[{user_id}] NEXT_ACTION: {captured['next_action']}")

        # 7. Verify email via D1
        log(f"[{user_id}] Waiting for verification email...")
        link = poll_verify_link(email)
        if not link:
            log(f"[{user_id}] No verification email (timeout)", "ERROR")
            browser.close()
            return None, "no_email"
        log(f"[{user_id}] Verification link found")
        page.goto(link, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(4000)
        log(f"[{user_id}] Email verified")

        # 8. Create API key via browser fetch (uses session cookies)
        log(f"[{user_id}] Creating API key via browser session...")
        api_key = page.evaluate("""async () => {
            try {
                // Clean up auto-created keys first
                const r0 = await fetch('/api/keys', {headers:{'Accept':'application/json'}, credentials:'same-origin'});
                if (r0.ok) {
                    const d0 = await r0.json();
                    for (const k of (d0.keys||[])) {
                        await fetch('/api/keys/' + k.id, {method:'DELETE', credentials:'same-origin'});
                    }
                }
                // Create new key
                const r = await fetch('/api/keys', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json', 'Accept':'application/json'},
                    credentials: 'same-origin',
                    body: JSON.stringify({label: 'th-' + Math.floor(Math.random()*900+100)})
                });
                if (r.ok) { const d = await r.json(); return d.plaintext || null; }
                return null;
            } catch(e) { return 'ERR:' + e.message; }
        }""")

        if not api_key or api_key.startswith("ERR"):
            log(f"[{user_id}] API key creation failed: {api_key}", "ERROR")
            browser.close()
            return None, "key_create_failed"
        log(f"[{user_id}] Key: {api_key[:35]}...")

        # 9. Accept free model consent
        consent = page.evaluate("""async () => {
            const r = await fetch('/api/me/privacy', {
                method: 'POST',
                headers: {'Content-Type':'application/json', 'Accept':'application/json'},
                credentials: 'same-origin',
                body: JSON.stringify({free_models_enabled: true})
            });
            return r.ok;
        }""")
        log(f"[{user_id}] Consent: {'Y' if consent else 'N'}")

        browser.close()

    return {
        "email": email, "password": pwd, "api_key": api_key,
        "verified": True, "consent": consent, "domain": domain
    }, None

# ===== TEST MODEL =====
def test_model(api_key, model=TEST_MODEL):
    try:
        r = requests.post(f"{BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30, json={"model": model, "messages": [{"role": "user", "content": "say ok"}], "max_tokens": 20})
        return (True, "200 OK") if r.status_code == 200 else (False, f"{r.status_code}")
    except Exception as e:
        return False, str(e)[:40]

# ===== 9ROUTER INJECT =====
def inject_9router(api_key, email):
    try:
        conn = sqlite3.connect(NINE_DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM providerConnections WHERE provider='tokenbor'")
        count = cur.fetchone()[0]
        now = datetime.now(timezone.utc).isoformat()
        label = f"{email.split('@')[0][:6]} #{count+1}"
        data = json.dumps({"defaultModel": TEST_MODEL, "apiKey": api_key, "testStatus": "active",
            "providerSpecificData": {"prefix": "tokenbor", "apiType": "chat",
                "baseUrl": "https://tokenharbor.ai/v1", "nodeName": "tokenbor"}})
        cur.execute("INSERT INTO providerConnections (id,provider,authType,name,email,priority,isActive,data,createdAt,updatedAt) VALUES (?,  'tokenbor','api_key',?,?,0,1,?,?,?)",
            (str(uuid.uuid4()), label, email, data, now, now))
        conn.commit(); conn.close()
        return True, label
    except Exception as e:
        return False, str(e)[:60]

# ===== STORAGE =====
ACCOUNT_FILE = Path(__file__).parent / "accounts.json"
APIKEY_FILE = Path(__file__).parent / "apikeys.txt"
def load_keys():
    return [l.strip() for l in APIKEY_FILE.read_text().splitlines() if l.strip()] if APIKEY_FILE.exists() else []
def save_key(key):
    with open(APIKEY_FILE, "a") as f: f.write(f"{key}\n")
def load_accounts():
    return json.loads(ACCOUNT_FILE.read_text()) if ACCOUNT_FILE.exists() else []
def save_accounts(data):
    ACCOUNT_FILE.write_text(json.dumps(data, indent=2))

# ===== BATCH =====
def run_batch(n):
    success = 0; rate_limited = 0
    for i in range(n):
        domain = DOMAINS[i % len(DOMAINS)]
        print(f"\n  [{i+1}/{n}] " + "="*40)
        log(f"Domain: {domain}")
        account, err = browser_signup_one(domain, f"acc-{i+1}")
        if account:
            accounts = load_accounts(); accounts.append(account); save_accounts(accounts)
            save_key(account["api_key"])
            success += 1
            ok, info = test_model(account["api_key"])
            log(f"Test {TEST_MODEL}: {'OK' if ok else 'FAIL'} {info}")
            inj, msg = inject_9router(account["api_key"], account["email"])
            log(f"Inject: {'OK' if inj else 'FAIL'} {msg}")
        else:
            rate_limited += 1
            if err in ("human_check", "no_email"):
                log("Rate-limit detected — stopping batch", "WARN")
                break
        if i < n - 1:
            wait = ACCOUNT_DELAY + random.randint(-10, 15)
            log(f"Waiting {wait}s...")
            time.sleep(wait)
    log(f"Done: {success}/{n} ok, {rate_limited} rate-limited")
    return success

# ===== COMMANDS =====
def cmd_monitor():
    conn = sqlite3.connect(NINE_DB)
    rows = conn.execute("SELECT name,email,isActive FROM providerConnections WHERE provider='tokenbor'").fetchall()
    keys = load_keys(); total_paths = 0
    print(f"\n  ╔══════════════════════════════════════════════════╗")
    print(f"  ║  TOKENHARBOR POOL — Health Check                ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    print(f"  ║  Akun di 9Router : {len(rows):>3}                          ║")
    print(f"  ║  Key di file     : {len(keys):>3}                          ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    for r in rows:
        tag = "🟢 aktif" if r[2] else "🔴 mati"
        print(f"  ║  {tag}  {r[0]:<18} {(r[1] or '')[:25]:<25} ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    if keys:
        for m in FREE_MODELS:
            valid, _ = test_model(keys[0], m)
            tag = "🟢 hidup" if valid else "🔴 mati"
            paths = len(rows) if valid else 0; total_paths += paths
            print(f"  ║    {tag}  {m.replace(':free',''):<25} {paths:>2} jalur   ║")
    print(f"  ╠══════════════════════════════════════════════════╣")
    print(f"  ║  Total jalur API gratis : {total_paths:>3}                ║")
    print(f"  ╚══════════════════════════════════════════════════╝")
    print()

def cmd_test():
    keys = load_keys()
    if not keys: print("\n  Tidak ada key di apikeys.txt"); return
    col_w, key_w = 18, 15
    header = f"  {'Key':<{key_w}}" + "".join(f"{m:<{col_w}}" for m in FREE_MODELS)
    print(f"\n  Test semua key x semua model:"); print(f"  {'—'*len(header)}")
    print(header); print(f"  {'—'*len(header)}")
    totals = {m: 0 for m in FREE_MODELS}
    for k in keys:
        row = f"  {k[10:25]:<{key_w}}"
        for m in FREE_MODELS:
            valid, _ = test_model(k, m)
            row += f"{'OK' if valid else 'FAIL':<{col_w}}"
            if valid: totals[m] += 1
        print(row)
    print(f"  {'—'*len(header)}")
    total_row = f"  {'TOTAL':<{key_w}}"
    for m in FREE_MODELS:
        total_row += f"{totals[m]}/{len(keys):<{col_w}}"
    print(total_row); print()

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python token_browser.py [batch N | test | monitor]")
    elif args[0] == "batch":
        run_batch(int(args[1]) if len(args) > 1 else 5)
    elif args[0] == "test":
        cmd_test()
    elif args[0] == "monitor":
        cmd_monitor()
    else:
        print(f"Unknown: {args[0]}")
