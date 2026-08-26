"""TokenHarbor signup — hybrid Turnstile solver.
Strategy: camofox click Turnstile checkbox first; fallback to YesCaptcha API if token empty.
"""
import json, time, random, string, uuid, re, sys, subprocess, os
import urllib.request, urllib.error
import requests

# === Config ===
CAMOFOX = "http://localhost:9377"
TH_BASE = "https://tokenharbor.ai"
YES_CLIENT = os.environ.get("YES_CLIENT", "")  # YesCaptcha ClientKey, set via env (never hardcode)
WORKER_DIR = r"C:\Users\TUF Gaming A15\cloud-mail-inspect\mail-worker"
NPX = r"C:\Users\TUF Gaming A15\AppData\Local\hermes\node\npx.cmd"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ACTION_ID = "607ec2c1a962aa81ad67a2483c54b0cfadfda875b2"
ACTION_KEY = "kb59e6b88b9f36883e58e38e7e48870c6"
NEXT_ACTION = ACTION_ID
ROUTER = '[["",{"children":["login",{"children":["__PAGE__",{},null,null,0]},null,null,20]},null,null,20]'

DOMAINS = ["ternakakun.biz.id", "infrasync.web.id", "schemacanvas.my.id", "hafizhmuzani.my.id", "azfa.biz.id"]

def cf_post(path, payload):
    req = urllib.request.Request(f"{CAMOFOX}{path}", data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)[:200]}

def cf_get(path):
    try:
        with urllib.request.urlopen(f"{CAMOFOX}{path}", timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:200]}

def evaluate(tab_id, user_id, expr):
    return cf_post(f"/tabs/{tab_id}/evaluate", {"userId": user_id, "expression": expr})

def snapshot(tab_id, user_id):
    return cf_get(f"/tabs/{tab_id}/snapshot?userId={user_id}")

def click_sel(tab_id, user_id, selector):
    return cf_post(f"/tabs/{tab_id}/click", {"userId": user_id, "selector": selector})

def gen_email(domain):
    u = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"th{u}@{domain}"

def rand_pwd():
    return "Th" + ''.join(random.choices(string.ascii_letters + string.digits, k=14)) + "!"

def yes_create_task(sitekey, url):
    payload = json.dumps({
        "clientKey": YES_CLIENT,
        "task": {"type": "TurnstileTaskProxyless", "websiteURL": url, "websiteKey": sitekey}
    })
    req = urllib.request.Request("https://api.yescaptcha.com/createTask",
                                 data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def yes_get_result(task_id):
    for _ in range(20):
        time.sleep(5)
        payload = json.dumps({"clientKey": YES_CLIENT, "taskId": task_id})
        req = urllib.request.Request("https://api.yescaptcha.com/getTaskResult",
                                     data=payload.encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        if data.get("status") == "ready":
            return data.get("solution", {})
        if data.get("errorId", 0) != 0:
            return None
    return None

def get_sitekey_from_network(tab_id, user_id):
    expr = """(function(){
      var entries = performance.getEntriesByType('resource') || [];
      for (var i = entries.length - 1; i >= 0; i--) {
        var u = entries[i].name || '';
        if (u.indexOf('turnstile') !== -1 && u.indexOf('sitekey=') !== -1) {
          var m = u.match(/sitekey=([^&]+)/);
          if (m) return m[1];
        }
      }
      return null;
    })()"""
    r = evaluate(tab_id, user_id, expr)
    return r.get("result")

def solve_turnstile(tab_id, user_id):
    """Click Turnstile checkbox via camofox; fallback YesCaptcha."""
    # Scroll form into view
    evaluate(tab_id, user_id, "window.scrollTo(0, document.querySelector('form') ? document.querySelector('form').offsetTop : 0)")
    time.sleep(2)

    # Click checkbox — try multiple selectors (iframe + shadow)
    selectors = [
        "iframe[src*='turnstile']",
        ".cf-turnstile",
        "button:has-text('Verify you are human')",
        "#cf-chl-widget-arwae",
    ]
    for sel in selectors:
        r = click_sel(tab_id, user_id, sel)
        if r.get("ok"):
            break
    # Also try clicking via evaluate inside iframe
    evaluate(tab_id, user_id, """(function(){
      try {
        var ifr = document.querySelector('iframe[src*="turnstile"]');
        if (ifr && ifr.contentDocument) {
          var cb = ifr.contentDocument.querySelector('input[type=checkbox], .checkbox, #checkbox');
          if (cb) cb.click();
        }
      } catch(e) {}
    })()""")
    time.sleep(8)

    # Poll token
    for _ in range(6):
        r = evaluate(tab_id, user_id, "document.querySelector('input[name=cf-turnstile-response]') ? document.querySelector('input[name=cf-turnstile-response]').value : ''")
        tok = r.get("result", "")
        if tok and len(tok) > 20:
            return tok, "camofox"
        time.sleep(4)

    # Fallback YesCaptcha
    sitekey = get_sitekey_from_network(tab_id, user_id)
    if not sitekey:
        return None, "no_sitekey"
    try:
        task = yes_create_task(sitekey, f"{TH_BASE}/login?mode=signup")
        if task.get("taskId"):
            sol = yes_get_result(task["taskId"])
            if sol and sol.get("token"):
                # Inject token
                evaluate(tab_id, user_id, f"""((function(){{var i=document.querySelector('input[name=cf-turnstile-response]');if(i){{i.value='{sol['token']}';i.dispatchEvent(new Event('input',{{bubbles:true}}));i.dispatchEvent(new Event('change',{{bubbles:true}}));}}}})())""")
                return sol["token"], "yescaptcha"
    except Exception as e:
        return None, f"yes_err:{e}"
    return None, "failed"

def submit_signup(email, pwd, turnstile_token):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.get(f"{TH_BASE}/login", timeout=20)
    fp = str(uuid.uuid4())
    bd = "------WebKitFormBoundary" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
    parts = []
    def af(n, v=""):
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}')
    af("1_$ACTION_REF_1")
    af("1_$ACTION_1:0", json.dumps({"id": ACTION_ID, "bound": "$@1"}))
    af("1_$ACTION_1:1", '["$undefined"]')
    af("1_$ACTION_KEY", ACTION_KEY)
    af("1_device_fingerprint", fp)
    af("1_timezone", "Asia/Jakarta")
    af("1_next")
    af("1_email", email)
    af("1_password", pwd)
    af("1_invite_code")
    af("0", '["$undefined","$K1"]')
    # Inject turnstile token
    af("cf-turnstile-response", turnstile_token)
    body = "\r\n".join(parts) + f"\r\n--{bd}--\r\n"
    headers = {
        "Content-Type": f"multipart/form-data; boundary={bd}",
        "Accept": "text/x-component",
        "Next-Action": NEXT_ACTION,
        "Next-Router-State-Tree": ROUTER,
        "Origin": TH_BASE,
        "Referer": f"{TH_BASE}/login?mode=signup",
    }
    r = s.post(f"{TH_BASE}/login", data=body, headers=headers, timeout=25)
    return r.text

if __name__ == "__main__":
    user_id = f"th_{uuid.uuid4().hex[:8]}"
    domain = DOMAINS[random.randint(0, len(DOMAINS)-1)]
    email = gen_email(domain)
    pwd = rand_pwd()
    print(f"[*] Account: {email}")

    # Create tab
    r = cf_post("/tabs", {"userId": user_id, "sessionKey": user_id, "url": f"{TH_BASE}/login?mode=signup"})
    if "error" in r:
        print("TAB ERR:", r)
        sys.exit(1)
    tab_id = r.get("tabId")
    print(f"[*] Tab: {tab_id}")

    time.sleep(5)
    # Dismiss cookie if present
    click_sel(tab_id, user_id, "button:has-text('Essential only')")
    time.sleep(1)

    tok, method = solve_turnstile(tab_id, user_id)
    print(f"[*] Turnstile: {method} -> {'(got token)' if tok else 'FAILED'}")

    if not tok:
        print("[!] Turnstile solve failed")
        sys.exit(1)

    resp = submit_signup(email, pwd, tok)
    print("[*] Signup response:", resp[:300])
    if "signedIn" in resp or "userId" in resp:
        print(f"[+] SUCCESS: {email}")
    else:
        print("[!] FAILED")
