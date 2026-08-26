"""
submit_manager_runner.py — TokenHarbor signup driver using in-page submit-manager.js

Flow:
  1. Open a Camoufox tab at the signup URL, dismiss the cookie banner.
  2. Inject submit_manager.js (the in-page watcher) and start it with the
     target email/password. The manager polls input[name=cf-turnstile-response]
     and auto-submits the form (via form.requestSubmit) the moment the token is
     populated AND the email/password fields exist/fillable.
  3. Solve Turnstile: click the widget (Camoufox invisible-pass path, which makes
     React reveal the email/password fields). Fallback to YesCaptcha token
     injection if the native solve doesn't populate the field.
  4. Poll window.__submitManager.status() until state == 'done' or timeout.

The Native solve path is preferred: when Camoufox passes the Turnstile challenge,
React re-renders the form with email/password fields, and the submit-manager
fires the Server Action automatically.

Usage:
  python submit_manager_runner.py                 # 1 random account
  python submit_manager_runner.py --email a@b.com --password 'Pw123!xyz'
  python submit_manager_runner.py --batch 3       # 3 sequential accounts
"""
import json
import time
import random
import string
import uuid
import sys
import urllib.request
import urllib.error
import argparse

# === Config ===
CAMOFOX = "http://localhost:9377"
TH_BASE = "https://tokenharbor.ai"
PROXY_BASE = "https://tokenharbor-proxy.hafizmuzani011.workers.dev"
SIGNUP_URL = f"{PROXY_BASE}/login?mode=signup"
YES_CLIENT = os.environ.get("YES_CLIENT", "")  # YesCaptcha ClientKey, set via env (never hardcode)
DOMAINS = ["ternakakun.biz.id", "infrasync.web.id",
           "schemacanvas.my.id", "hafizhmuzani.my.id", "azfa.biz.id"]

SUBMIT_MANAGER_JS = open(__file__.replace("submit_manager_runner.py",
                       "submit_manager.js"), encoding="utf-8").read()


# --------------------------------------------------------------------------- #
# Camofox REST helpers
# --------------------------------------------------------------------------- #
def cf_post(path, body):
    req = urllib.request.Request(f"{CAMOFOX}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:300]}
    except Exception as e:
        return {"error": str(e)[:300]}


def cf_get(path):
    try:
        with urllib.request.urlopen(f"{CAMOFOX}{path}", timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)[:300]}


def evaluate(tab_id, user_id, expr):
    return cf_post(f"/tabs/{tab_id}/evaluate", {"userId": user_id, "expression": expr})


def snapshot(tab_id, user_id):
    return cf_get(f"/tabs/{tab_id}/snapshot?userId={user_id}")


def new_tab(user_id):
    r = cf_post("/tabs", {"userId": user_id, "sessionKey": user_id, "url": SIGNUP_URL})
    if "error" in r or not r.get("tabId"):
        raise RuntimeError(f"tab create failed: {r}")
    return r["tabId"]


# --------------------------------------------------------------------------- #
# YesCaptcha fallback (turnstile token)
# --------------------------------------------------------------------------- #
def yes_create_task(sitekey, url):
    payload = json.dumps({"clientKey": YES_CLIENT,
                          "task": {"type": "TurnstileTaskProxyless",
                                   "websiteURL": url, "websiteKey": sitekey}})
    req = urllib.request.Request("https://api.yescaptcha.com/createTask",
                                 data=payload.encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def yes_get_result(task_id):
    for _ in range(24):
        time.sleep(5)
        payload = json.dumps({"clientKey": YES_CLIENT, "taskId": task_id})
        req = urllib.request.Request("https://api.yescaptcha.com/getTaskResult",
                                     data=payload.encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        if data.get("status") == "ready":
            return data.get("solution", {}).get("token")
        if data.get("errorId", 0) != 0:
            return None
    return None


def get_sitekey(tab_id, user_id):
    """Extract Turnstile sitekey from page resources. Two patterns:
    1. `sitekey=` query param (when widget initializes with explicit key)
    2. challenge-platform path segment of the form `/<sitekey>/auto/...`
       (verifiable on live TokenHarbor: 0x4AAAAAADBuC8Knz1EJZx9-)"""
    expr = """(function(){
      var entries = performance.getEntriesByType('resource') || [];
      var seen = [];
      for (var i = entries.length - 1; i >= 0; i--) {
        var u = entries[i].name || '';
        if (u.indexOf('turnstile') === -1 && u.indexOf('challenge-platform') === -1) continue;
        seen.push(u.slice(0, 160));
        var q = u.match(/sitekey=([^&]+)/);
        if (q) return 'SITEKEY:' + q[1];
        var path = u.match(/challenge-platform\\/h\\/b\\/turnstile\\/[^/]+\\/([0-9A-Za-z_-]{10,})\\/auto\\//);
        if (path) return 'SITEKEY:' + path[1];
      }
      return 'NONE:' + seen.join('|');
    })()"""
    r = evaluate(tab_id, user_id, expr).get("result") or ""
    if r.startswith("SITEKEY:"):
        return r[8:]
    # hard fallback: TokenHarbor's known key (re-verify if build changes)
    if "0x4AAAAAADBuC8Knz1EJZx9-" in r:
        return "0x4AAAAAADBuC8Knz1EJZx9-"
    return None


# --------------------------------------------------------------------------- #
# Submit manager wiring
# --------------------------------------------------------------------------- #
def inject_manager(tab_id, user_id):
    r = evaluate(tab_id, user_id, SUBMIT_MANAGER_JS)
    return r.get("ok")


def start_manager(tab_id, user_id, email, password):
    cfg = json.dumps({"email": email, "password": password, "autoFill": True,
                      "maxWaitMs": 180000, "pollMs": 150})
    r = evaluate(tab_id, user_id, f"window.__submitManager.start({cfg})")
    return r.get("result")


def manager_status(tab_id, user_id):
    r = evaluate(tab_id, user_id, "JSON.stringify(window.__submitManager.status())")
    try:
        return json.loads(r.get("result", "{}"))
    except Exception:
        return {"raw": r}


# --------------------------------------------------------------------------- #
# Turnstile solving — make the token appear
# --------------------------------------------------------------------------- #
def solve_turnstile(tab_id, user_id, email, password):
    """Return (ok, method). The in-page manager handles submission once the
    token is present; this function only makes the token appear."""
    # 1) Native click path (Camoufox invisible-pass). This also reveals fields.
    evaluate(tab_id, user_id,
             "var w=document.querySelector('.my-3.flex.justify-center > div');"
             "if(w)w.click();")
    for _ in range(8):
        time.sleep(3)
        st = manager_status(tab_id, user_id)
        if st.get("tokenLen", 0) > 20:
            return True, "camofox"

    # 2) YesCaptcha fallback — inject token into the hidden field.
    sitekey = get_sitekey(tab_id, user_id)
    if not sitekey:
        return False, "no_sitekey"
    task = yes_create_task(sitekey, SIGNUP_URL)
    if not task.get("taskId"):
        return False, "yes_create_failed"
    tok = yes_get_result(task["taskId"])
    if not tok:
        return False, "yes_no_token"
    # Fire React's onVerified(token) via the Fiber tree — setting input.value
    # alone does NOT trigger the React callback, so the 2-phase form never
    # advances. Walking memoizedProps for onVerified is build-hash agnostic.
    fire = """(function(tok){
      var el = document.querySelector('input[name=cf-turnstile-response]');
      var node = el && el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement : null;
      if (!node) return 'NO_NODE';
      var fk = null;
      for (var k in node) { if (k.indexOf('__reactFiber') === 0) { fk = k; break; } }
      if (!fk) return 'NO_FIBER';
      var f = node[fk], depth = 0;
      while (f && depth < 30) {
        var p = f.memoizedProps;
        if (p && typeof p.onVerified === 'function') {
          try { p.onVerified(tok); return 'FIRED_depth' + depth; } catch (e) { return 'ERR:' + e.message; }
        }
        f = f.return; depth++;
      }
      return 'NO_ONVERIFIED';
    })(%s)""" % json.dumps(tok)
    r = evaluate(tab_id, user_id, fire)
    fired = (r.get("result") or "")
    if not fired.startswith("FIRED"):
        return False, f"fire_failed:{fired}"
    return True, f"yescaptcha+fiber ({fired})"


# --------------------------------------------------------------------------- #
# Account generation
# --------------------------------------------------------------------------- #
def gen_email(domain):
    u = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"th{u}@{domain}"


def rand_pwd():
    return "Th" + ''.join(random.choices(string.ascii_letters + string.digits, k=14)) + "!"


# --------------------------------------------------------------------------- #
# One account
# --------------------------------------------------------------------------- #
def run_one(email=None, password=None):
    user_id = f"th_{uuid.uuid4().hex[:8]}"
    if email is None:
        email = gen_email(DOMAINS[random.randint(0, len(DOMAINS) - 1)])
    if password is None:
        password = rand_pwd()
    print(f"[*] {email}")

    tab = new_tab(user_id)
    time.sleep(5)

    # dismiss cookie banner
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Essential only')"})
    time.sleep(1)
    # ensure Sign up tab active (mode=signup already in URL, but click to be safe)
    cf_post(f"/tabs/{tab}/click", {"userId": user_id, "selector": "button:has-text('Sign up')"})
    time.sleep(2)

    # ── NEW: check if captcha is needed (precheck via proxy) ──
    need_captcha = evaluate(tab, user_id,
        "var f=document.querySelector('input[name=cf-turnstile-response]');"
        "JSON.stringify({need: !!f})").get("result", "{}")
    try:
        need_captcha = json.loads(need_captcha).get("need", True)
    except Exception:
        need_captcha = True

    inject_manager(tab, user_id)
    if need_captcha:
        start_manager(tab, user_id, email, password)
        print(f"[*] submit-manager watching (tab={tab})")
        ok, method = solve_turnstile(tab, user_id, email, password)
        print(f"[*] turnstile: {method}")
        if not ok:
            st = manager_status(tab, user_id)
            print(f"[!] turnstile solve failed — manager state: {st.get('state')}")
            return {"email": email, "ok": False, "reason": "turnstile_failed"}
    else:
        # Captcha skipped (proxy egress IP is clean). Manager auto-fills
        # email/password (fields already present) and submits on its own.
        print(f"[*] needCaptcha=false — direct submit via proxy")
        start_manager(tab, user_id, email, password)

    # wait for the manager to submit
    for _ in range(60):  # up to 90s
        time.sleep(1.5)
        st = manager_status(tab, user_id)
        if st.get("state") in ("done", "failed"):
            break

    st = manager_status(tab, user_id)
    print(f"[*] manager final: {st.get('state')}")

    # wait for navigation to dashboard (signup → /dashboard or /onboarding)
    time.sleep(6)

    # verify outcome from the page
    verdict = evaluate(tab, user_id, "document.body.innerText.slice(0,500)").get("result", "")
    vl = verdict.lower()
    success = ("verify your email" in vl or "check your email" in vl
               or "signed in" in vl or "welcome" in vl
               or "we sent" in vl or "confirm" in vl
               or "your account" in vl or "success" in vl
               or "overview" in vl or "billing" in vl or "api key" in vl)
    # also pass if the email/password fields / signup form have been replaced
    fields_gone = not evaluate(tab, user_id,
        "JSON.stringify(!!document.querySelector('input[name=email]'))").get("result")
    if not success and fields_gone:
        success = True
    return {"email": email, "ok": success, "state": st.get("state"),
            "verdict": verdict[:160]}


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--batch", type=int, default=1)
    args = ap.parse_args()

    results = []
    n = args.batch if args.email is None else 1
    for i in range(n):
        if i:
            time.sleep(8)
        try:
            res = run_one(args.email, args.password)
        except Exception as e:
            res = {"email": args.email, "ok": False, "reason": str(e)[:200]}
        results.append(res)
        print(f"[{'OK' if res.get('ok') else 'FAIL'}] {res.get('email')} :: {res.get('state') or res.get('reason')}")

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n=== {ok}/{len(results)} succeeded ===")


if __name__ == "__main__":
    main()
