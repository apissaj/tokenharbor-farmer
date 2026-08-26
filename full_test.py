"""
full_test.py — Build one account, harvest API key, call model.
All in one Camofox session — no navigate, only click.
"""
import sys, json, time, uuid, urllib.request, urllib.parse
sys.path.insert(0, 'D:/tokenharbor-farmer')
from submit_manager_runner import (evaluate, new_tab, cf_post, cf_get, inject_manager,
    start_manager, manager_status, gen_email, rand_pwd, PROXY_BASE, CAMOFOX)

user_id = f'th_{uuid.uuid4().hex[:8]}'
email = gen_email('hafizhmuzani.my.id')
pw = rand_pwd()
print(f'ACCOUNT: {email} / {pw}')

# ── 1. Signup (same as run_one no-captcha path) ──
tab = new_tab(user_id)
print('tab:', tab)
time.sleep(6)

# dismiss cookie
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Essential only')"})
time.sleep(1)
# click signup
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Sign up')"})
time.sleep(2)

# inject manager + start
inject_manager(tab, user_id)
start_manager(tab, user_id, email, pw)
print('manager started')

# wait for submit
for i in range(30):
    time.sleep(3)
    st = manager_status(tab, user_id)
    print(f'  {i*3}s: {st.get("state")} tok={st.get("tokenLen")} email={st.get("hasEmail")} pw={st.get("hasPassword")}')
    if st.get('state') in ('done', 'failed'):
        break
print(f'manager: {st.get("state")}')

# wait for dashboard navigation
time.sleep(8)

# confirm we're on dashboard
body = evaluate(tab, user_id, 'document.body.innerText.slice(0,400)').get('result','')
print('dashboard:', body[:200])

# ── 2. Click API Key link (from sidebar) ──
# Try clicking the API Key link in the sidebar
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "a[href*='api-keys']:has-text('API Key')"})
time.sleep(6)

# Check if we're on API keys page
body = evaluate(tab, user_id, 'document.body.innerText.slice(0,600)').get('result','')
print('after api-key click:', body[:200])

# Try clicking + New key
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('New key')"})
time.sleep(4)

# Fill label
evaluate(tab, user_id, """(function(){
  var inputs = Array.prototype.slice.call(document.querySelectorAll('input'));
  var target = null;
  for (var i=0;i<inputs.length;i++){
    var ph = (inputs[i].placeholder||'') + (inputs[i].name||'') + (inputs[i].id||'');
    if (/label|name/i.test(ph)) { target = inputs[i]; break; }
  }
  if (!target) target = inputs[0];
  if (!target) return JSON.stringify({err:'no_input'});
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(target, 'farm9router');
  target.dispatchEvent(new Event('input',{bubbles:true}));
  target.dispatchEvent(new Event('change',{bubbles:true}));
  return JSON.stringify({filled:true,val:target.value});
})()""")
time.sleep(1)

# Click Create key button
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Create key')"})
time.sleep(8)

# Harvest key
harvest = evaluate(tab, user_id, """(function(){
  var patterns = [/th_[A-Za-z0-9_\\-]{10,}/g, /sk-[A-Za-z0-9_\\-]{10,}/g, /[a-zA-Z0-9]{30,}/g];
  var found = [];
  var txt = document.body.innerText + ' ' + document.body.innerHTML;
  for (var i=0;i<patterns.length;i++){
    var m = txt.match(patterns[i]);
    if (m) found = found.concat(m);
  }
  var unique = Array.from(new Set(found)).filter(function(s){return s.length>15}).slice(0,10);
  var codes = Array.prototype.slice.call(document.querySelectorAll('code,pre')).map(function(c){return (c.textContent||'').trim()}).filter(function(s){return s.length>10}).slice(0,5);
  return JSON.stringify({found:unique, codes:codes});
})()""").get('result', '{}')
print('harvest:', harvest)

# ── 3. If we got a key, test the model ──
try:
    h = json.loads(harvest)
    key = None
    for k in h.get('found', []):
        if k.startswith('th_') or k.startswith('sk-'):
            key = k
            break
    if not key and h.get('codes'):
        key = h['codes'][0]
    if key:
        print(f'\n--- Testing model with key: {key[:30]}... ---')
        # test via proxy (same CF egress IP)
        payload = json.dumps({
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "Say 'hello from tokenharbor'"}],
            "max_tokens": 50
        })
        req = urllib.request.Request(
            f"{PROXY_BASE}/v1/chat/completions",
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "Origin": PROXY_BASE,
                "Referer": f"{PROXY_BASE}/"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        print('model response:', json.dumps(resp, indent=2)[:500])
    else:
        print('No API key found to test')
except Exception as e:
    print(f'test error: {e}')

# Save results
with open('D:/tokenharbor-farmer/accounts.json', 'a') as f:
    f.write(json.dumps({'email': email, 'password': pw, 'harvest': harvest, 'ts': time.time()}) + '\n')
print('done')