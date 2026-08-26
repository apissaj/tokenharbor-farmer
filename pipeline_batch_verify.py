"""pipeline_batch_verify.py — TokenHarbor account factory, batch-verify strategy.

Phase 1: signup N accounts sequentially (fast, no email wait), close each tab.
Phase 2: wait for ALL verification emails in D1 (batch poll, no per-account stall).
Phase 3: per account — click verify link, login, harvest API key, enable free, test 3 models.

Why: sequential verify (pipeline.py) idles 60-120s per account waiting for email.
Batch-verify overlaps that wait across accounts -> ~2x faster.

Usage: python pipeline_batch_verify.py --batch 10 --delay 15
"""
import sys, os, json, time, uuid, re, subprocess, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from submit_manager_runner import (
    evaluate, cf_post, new_tab, inject_manager, start_manager, manager_status,
    gen_email, rand_pwd, PROXY_BASE, CAMOFOX,
)

ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
WORKER_DIR = os.path.expanduser("~/cloud-mail-inspect/mail-worker")
MODELS = ["deepseek-v4-flash:free", "mimo-v2.5:free", "qwen3.8-27b:free"]


def log_account(rec):
    with open(ACCOUNTS_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")


def signup_only():
    """Signup one account, then close the tab. Returns (email, password) or (None, None)."""
    for attempt in range(2):
        email = gen_email("hafizhmuzani.my.id")
        password = rand_pwd()
        user_id = f"th_{uuid.uuid4().hex[:8]}"
        print(f"[*] signup {email}" + (f" (retry {attempt+1})" if attempt else ""))
        try:
            tab = new_tab(user_id)
            if not tab:
                continue
            time.sleep(6)
            cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Essential only')"})
            time.sleep(1)
            cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Sign up')"})
            time.sleep(2)
            inject_manager(tab, user_id)
            start_manager(tab, user_id, email, password)
            done = False
            for _ in range(25):
                time.sleep(3)
                st = manager_status(tab, user_id)
                if st.get("state") in ("done", "failed"):
                    done = st.get("state") == "done"
                    break
            cf_post(f"/tabs/{tab}/close", {"userId": user_id})
            if done:
                return email, password
        except Exception as e:
            print(f"[!] signup error: {e}")
    return None, None


def collect_verify_links(emails, max_wait=360):
    """Poll D1 until every email has a verify link. Returns dict email -> link."""
    links = {}
    deadline = time.time() + max_wait
    pattern = re.compile(r"https?://tokenharbor\.ai/verify[-_a-zA-Z]*\?token=[^\s\"<>]+")
    print(f"[*] waiting for {len(emails)} verification emails (up to {max_wait // 60} min)...")
    while time.time() < deadline:
        missing = [e for e in emails if e not in links]
        if not missing:
            break
        try:
            in_clause = "','".join(e.replace("'", "''") for e in missing)
            cmd = ["cmd", "/c", "npx", "wrangler", "d1", "execute", "cloud-mail-db", "--remote",
                   "--command",
                   f"SELECT to_email, text FROM email WHERE to_email IN ('{in_clause}') AND text LIKE '%verify%' ORDER BY create_time DESC",
                   "--json"]
            result = subprocess.run(cmd, cwd=WORKER_DIR, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            rows = data[0]["results"] if isinstance(data, list) else data.get("results", [])
            for r in rows:
                email = r.get("to_email")
                text = r.get("text") or ""
                if email and email not in links:
                    m = pattern.search(text)
                    if m:
                        links[email] = m.group(0)
                        print(f"  ✓ link found: {email}")
        except Exception as e:
            print(f"[!] D1 poll error: {e}")
        time.sleep(10)
    return links


def click_verify_link(link):
    """Open verify link in a fresh tab (works without login), then close it."""
    user_id = f"th_verify_{uuid.uuid4().hex[:6]}"
    try:
        req = urllib.request.Request(
            f"{CAMOFOX}/tabs",
            data=json.dumps({"userId": user_id, "sessionKey": user_id, "url": link}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            tab = json.loads(r.read().decode())["tabId"]
        time.sleep(8)
        cf_post(f"/tabs/{tab}/close", {"userId": user_id})
        return True
    except Exception as e:
        print(f"[!] verify click error: {e}")
        return False


def login_tab(email, password):
    """Login via proxy, return (tab, user_id) or (None, None)."""
    user_id = f"th_login_{uuid.uuid4().hex[:6]}"
    try:
        req = urllib.request.Request(
            f"{CAMOFOX}/tabs",
            data=json.dumps({"userId": user_id, "sessionKey": user_id, "url": f"{PROXY_BASE}/login"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            tab = json.loads(r.read().decode())["tabId"]
    except Exception as e:
        print(f"[!] login open error: {e}")
        return None, None
    time.sleep(6)
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Essential only')"})
    time.sleep(1)
    evaluate(tab, user_id, """(function(email, pw){
      var e=document.querySelector('input[type=email]');
      var p=document.querySelector('input[type=password]');
      var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      setter.call(e, email); e.dispatchEvent(new Event('input',{bubbles:true})); e.dispatchEvent(new Event('change',{bubbles:true}));
      setter.call(p, pw); p.dispatchEvent(new Event('input',{bubbles:true})); p.dispatchEvent(new Event('change',{bubbles:true}));
      var f=document.querySelector('form'); var btn=f&&f.querySelector('button[type=submit]');
      if(btn)btn.click(); else if(f)f.requestSubmit();
    })(""" + json.dumps(email) + "," + json.dumps(password) + ")")
    time.sleep(10)
    url = evaluate(tab, user_id, "location.href").get("result", "")
    if "/dashboard" not in url:
        print(f"[!] login failed — still at {url}")
        cf_post(f"/tabs/{tab}/close", {"userId": user_id})
        return None, None
    return tab, user_id


def enable_free_models(tab, user_id):
    evaluate(tab, user_id, """(function(){
      var btns=Array.prototype.slice.call(document.querySelectorAll('button'));
      var b=btns.find(function(x){return /enable free models/i.test(x.textContent||'')});
      if(b){b.click();return true;}
      return false;
    })()""")
    time.sleep(5)


def harvest_api_key(tab, user_id):
    """Go to API keys, create a key, return the key string or None."""
    try:
        evaluate(tab, user_id, r"""(function(){
            var a=document.querySelector('a[href="/dashboard/api-keys"]');
            if(a)a.click();
        })()""")
        time.sleep(6)
        evaluate(tab, user_id, r"""(function(){
            var b=Array.prototype.slice.call(document.querySelectorAll('button')).find(function(x){return /New key/i.test(x.textContent||'')});
            if(b)b.click();
        })()""")
        time.sleep(4)
        evaluate(tab, user_id, r"""(function(){
            var inputs=Array.prototype.slice.call(document.querySelectorAll('input'));
            var t=inputs[0];
            if(!t)return;
            var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            setter.call(t,'farm9router');
            t.dispatchEvent(new Event('input',{bubbles:true}));
            t.dispatchEvent(new Event('change',{bubbles:true}));
        })()""")
        time.sleep(1)
        evaluate(tab, user_id, r"""(function(){
            var b=Array.prototype.slice.call(document.querySelectorAll('button')).find(function(x){return /Create key/i.test(x.textContent||'')});
            if(b)b.click();
        })()""")
        time.sleep(8)
        r = evaluate(tab, user_id, r"""(function(){
            var found=[];
            var txt=document.body.innerText+' '+document.body.innerHTML;
            var m=txt.match(/th_[A-Za-z0-9_\-]{10,}/g); if(m)found=found.concat(m);
            var codes=Array.prototype.slice.call(document.querySelectorAll('code,pre')).map(function(c){return (c.textContent||'').trim()});
            return JSON.stringify({keys:found,codes:codes});
        })()""").get("result", "{}")
        h = json.loads(r)
        for c in h.get("codes", []):
            if c.startswith("thk_live_") and "•" not in c:
                return c
        for k in h.get("keys", []):
            if k.startswith("thk_live_"):
                return k
    except Exception as e:
        print(f"[!] harvest error: {e}")
    return None


def test_model(api_key, model):
    payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "Say exactly: ok"}], "max_tokens": 30})
    req = urllib.request.Request(
        "https://tokenharbor.ai/v1/chat/completions",
        data=payload.encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        if "choices" in resp:
            return True
        return False
    except Exception:
        return False


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--delay", type=int, default=15)
    args = ap.parse_args()

    print(f"=== BATCH-VERIFY PIPELINE: {args.batch} accounts ===\n")

    # ---- Phase 1: signup all ----
    accounts = []
    for i in range(args.batch):
        if i:
            print(f"--- delay {args.delay}s ---")
            time.sleep(args.delay)
        email, password = signup_only()
        accounts.append({"email": email, "password": password})
        if email:
            print(f"  ✓ signup done")
        else:
            print(f"  ✗ signup FAILED (after retries)")

    ok_signup = sum(1 for a in accounts if a["email"])
    print(f"\n=== Phase 1 done: {ok_signup}/{args.batch} signed up ===")

    # ---- Phase 2: wait for all verify links ----
    emails = [a["email"] for a in accounts if a["email"]]
    links = collect_verify_links(emails)
    print(f"\n=== Phase 2 done: {len(links)}/{len(emails)} links ===")

    # ---- Phase 3: verify + harvest + enable + test per account ----
    results = []
    for a in accounts:
        email = a["email"]
        if not email:
            results.append({"email": None, "ok": False, "reason": "signup_failed"})
            continue
        print(f"\n[{email}]")
        link = links.get(email)
        if not link:
            results.append({**a, "ok": False, "reason": "no_verify_email"})
            continue
        print("  verify...")
        if not click_verify_link(link):
            results.append({**a, "ok": False, "reason": "verify_click_failed"})
            continue
        print("  login...")
        tab, uid = login_tab(email, a["password"])
        if not tab:
            results.append({**a, "ok": False, "reason": "login_failed"})
            continue
        print("  enable free...")
        enable_free_models(tab, uid)
        print("  harvest key...")
        key = harvest_api_key(tab, uid)
        cf_post(f"/tabs/{tab}/close", {"userId": uid})
        if not key:
            results.append({**a, "ok": False, "reason": "harvest_failed"})
            continue
        print(f"  ✓ key {key[:24]}...")
        tests = {}
        for m in MODELS:
            tests[m] = test_model(key, m)
        all_ok = all(tests.values())
        print(f"  tests: {tests}")
        rec = {**a, "api_key": key, "verified": True, "free_enabled": True, "tests": tests, "ok": all_ok}
        log_account(rec)
        results.append(rec)

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n=== {ok}/{args.batch} fully working ===")
    for r in results:
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  [{status}] {str(r.get('email'))[:35]}" +
              (f" key={r['api_key'][:24]}..." if r.get("api_key") else f" ({r.get('reason','')})"))


if __name__ == "__main__":
    main()