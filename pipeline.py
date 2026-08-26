"""pipeline.py — Full TokenHarbor account pipeline (signup → verify → enable → harvest → test).
One script, one session, no manual steps. Saves to accounts.json as structured record.
"""
import sys, json, time, uuid, urllib.request, re, os, subprocess

sys.path.insert(0, os.path.dirname(__file__) + '/..')
from submit_manager_runner import (evaluate, cf_post, cf_get, new_tab,
    inject_manager, start_manager, manager_status, gen_email, rand_pwd,
    PROXY_BASE, CAMOFOX)

ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), 'accounts.json')


def log_account(rec):
    with open(ACCOUNTS_FILE, 'a') as f:
        f.write(json.dumps(rec) + '\n')


def signup_one():
    """Create an account via proxy. Returns (email, password, user_id, tab)."""
    user_id = f"th_{uuid.uuid4().hex[:8]}"
    email = gen_email('hafizhmuzani.my.id')
    password = rand_pwd()
    print(f"[*] signup {email}")

    tab = new_tab(user_id)
    if not tab:
        print("[!] no tab returned")
        return email, password, user_id, None
    time.sleep(6)
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Essential only')"})
    time.sleep(1)
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Sign up')"})
    time.sleep(2)

    inject_manager(tab, user_id)
    start_manager(tab, user_id, email, password)
    for _ in range(25):
        time.sleep(3)
        st = manager_status(tab, user_id)
        if st.get("state") in ("done", "failed"):
            break
    time.sleep(8)
    # sanity: did we reach dashboard?
    url = evaluate(tab, user_id, "location.href").get("result", "")
    if "/dashboard" not in url:
        body = evaluate(tab, user_id, "document.body.innerText.slice(0,200)").get("result", "")
        print(f"[!] signup may have failed — url={url} body={body[:80]}")
    return email, password, user_id, tab


def harvest_api_key(tab, user_id):
    """Navigate to API keys, create key, return the key string or None."""
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
    harvest = evaluate(tab, user_id, r"""(function(){
        var found=[];
        var txt=document.body.innerText+' '+document.body.innerHTML;
        var m=txt.match(/th_[A-Za-z0-9_\-]{10,}/g); if(m)found=found.concat(m);
        var codes=Array.prototype.slice.call(document.querySelectorAll('code,pre')).map(function(c){return (c.textContent||'').trim()});
        return JSON.stringify({keys:found,codes:codes});
    })()""").get("result", "{}")
    try:
        h = json.loads(harvest)
    except Exception:
        return None
    # Prefer full thk_live_ key from code/pre elements
    for c in h.get("codes", []):
        if c.startswith("thk_live_") and "•" not in c:
            return c
    for k in h.get("keys", []):
        if k.startswith("thk_live_"):
            return k
    if h.get("codes"):
        return h["codes"][0]
    return None


def verify_email(email, api_key):
    """Poll D1 for the verification link, click it, then confirm via API.
    Ground truth = /v1/models no longer returns 'verify your email'."""
    print(f"[*] waiting for verification email for {email}")
    d1_dir = os.path.expanduser("~/cloud-mail-inspect/mail-worker")
    clicked = False
    for _ in range(40):
        # 1) Confirm verification via API first (fast path if already done)
        if clicked or True:
            t = test_models_list(api_key)
            if t is not None and "verify your email" not in t.lower():
                print("[*] account verified (API confirms)")
                return True
        # 2) Fetch link from D1
        if not clicked:
            try:
                result = subprocess.run(
                    ["cmd", "/c", "npx", "wrangler", "d1", "execute", "cloud-mail-db", "--remote",
                     "--command", f"SELECT text FROM email WHERE to_email='{email}' ORDER BY create_time DESC LIMIT 1",
                     "--json"],
                    cwd=d1_dir, capture_output=True, text=True, timeout=30)
                data = json.loads(result.stdout)
                rows = data[0]["results"] if isinstance(data, list) else data.get("results", [])
                if rows:
                    text = rows[0].get("text", "")
                    links = re.findall(r"https?://tokenharbor\.ai/verify-email\?token=[^\s\"<>]+", text)
                    if links:
                        verify_url = links[0]
                        print(f"[*] verify link found, opening...")
                        uid = f"th_verify_{uuid.uuid4().hex[:6]}"
                        req = urllib.request.Request(
                            f"{CAMOFOX}/tabs",
                            data=json.dumps({"userId": uid, "sessionKey": uid, "url": verify_url}).encode(),
                            headers={"Content-Type": "application/json"}
                        )
                        with urllib.request.urlopen(req, timeout=60) as r:
                            json.loads(r.read().decode())
                        clicked = True
                        time.sleep(8)
            except Exception as e:
                print(f"[!] verify poll error: {e}")
        time.sleep(5)
    return False


def test_models_list(api_key):
    """GET /v1/models. Returns response text or None on network error."""
    req = urllib.request.Request(
        "https://tokenharbor.ai/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()
    except Exception:
        return None


def login_and_enable_free(email, password):
    """Login via proxy, click Enable free models. Returns tab or None."""
    user_id = f"th_login_{uuid.uuid4().hex[:6]}"
    req = urllib.request.Request(
        f"{CAMOFOX}/tabs",
        data=json.dumps({"userId": user_id, "sessionKey": user_id,
                         "url": f"{PROXY_BASE}/login"}).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        tab = json.loads(r.read().decode())["tabId"]
    time.sleep(6)
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Essential only')"})
    time.sleep(1)
    # fill + submit
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
        return None
    print(f"[*] logged in")
    # enable free models
    enable = evaluate(tab, user_id, """(function(){
      var btns=Array.prototype.slice.call(document.querySelectorAll('button'));
      var b=btns.find(function(x){return /enable free models/i.test(x.textContent||'')});
      if(b){b.click();return true;}
      return false;
    })()""").get("result", "false")
    print(f"[*] enable free: {enable}")
    time.sleep(5)
    return tab


def test_model(api_key, model="deepseek-v4-flash:free"):
    """Test a model call. Returns response dict or error string."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say exactly: ok"}],
        "max_tokens": 30
    })
    req = urllib.request.Request(
        "https://tokenharbor.ai/v1/chat/completions",
        data=payload.encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        if "choices" in resp:
            return {"ok": True, "model": model, "content": resp["choices"][0]["message"]["content"][:60],
                    "usage": resp.get("usage", {})}
        return {"ok": False, "error": json.dumps(resp)[:200]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def run_one(email=None, password=None):
    """Full pipeline for one account. Returns result dict."""
    email, password, user_id, tab = signup_one()
    if not tab:
        return {"email": email, "ok": False, "reason": "signup_failed"}
    result = {"email": email, "password": password, "ts": time.time()}

    # harvest API key
    api_key = harvest_api_key(tab, user_id)
    result["api_key"] = api_key
    if not api_key:
        result["ok"] = False
        result["reason"] = "no_key"
        log_account(result)
        return result

    # verify email
    verified = verify_email(email, api_key)
    result["verified"] = verified
    if not verified:
        result["ok"] = False
        result["reason"] = "verify_failed"
        log_account(result)
        return result

    # login + enable free
    login_tab = login_and_enable_free(email, password)
    result["free_enabled"] = bool(login_tab)

    # test models
    tests = {}
    for m in ["deepseek-v4-flash:free", "mimo-v2.5:free", "qwen3.8-27b:free"]:
        t = test_model(api_key, m)
        tests[m] = t.get("ok", False)
        if t.get("ok"):
            tests[m + "_content"] = t.get("content", "")
    result["tests"] = tests
    result["ok"] = all(tests.values())
    log_account(result)
    return result


def main():
    import argparse
    ap = argparse.ArgumentParser(description="TokenHarbor account pipeline")
    ap.add_argument("--batch", type=int, default=1, help="Number of accounts to create")
    ap.add_argument("--delay", type=int, default=30, help="Delay between accounts (seconds)")
    args = ap.parse_args()

    results = []
    for i in range(args.batch):
        if i:
            print(f"\n--- waiting {args.delay}s before next account ---")
            time.sleep(args.delay)
        attempt = 0
        res = None
        while attempt < 2:
            attempt += 1
            try:
                res = run_one()
            except Exception as e:
                res = {"ok": False, "reason": str(e)[:200], "ts": time.time()}
            if res.get("ok") or attempt >= 2:
                break
            print(f"[!] attempt {attempt} failed ({res.get('reason','?')}), retrying...")
        results.append(res)
        status = "OK" if res.get("ok") else "FAIL"
        print(f"[{status}] {res.get('email')} key={str(res.get('api_key'))[:20]} free={res.get('free_enabled')} tests={res.get('tests')}")

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n=== {ok}/{len(results)} succeeded ===")


if __name__ == "__main__":
    main()
