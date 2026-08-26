"""Create a TokenHarbor account via proxy, then harvest its API key, all in one session."""
import sys, json, uuid, time, urllib.request, re

sys.path.insert(0, 'D:/tokenharbor-farmer')
from submit_manager_runner import (evaluate, new_tab, cf_post, inject_manager,
    start_manager, manager_status, gen_email, rand_pwd, PROXY_BASE)

def step(label, fn):
    print(f'-- {label} --')
    try:
        r = fn()
        print(f'   {r if isinstance(r, str) else json.dumps(r)[:400]}')
        return r
    except Exception as e:
        print(f'   ERR {e}')
        return None

user_id = f'th_{uuid.uuid4().hex[:8]}'
email = gen_email('hafizhmuzani.my.id')
pw = rand_pwd()
print(f'ACCOUNT: {email} / {pw}')

# 1. Open tab via proxy
tab = new_tab(user_id)
print('tab:', tab)
time.sleep(6)

# 2. Dismiss cookie + ensure signup
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Essential only')"})
time.sleep(1)
cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Sign up')"})
time.sleep(2)

# 3. Inject manager + start
inject_manager(tab, user_id)
start_manager(tab, user_id, email, pw)

# 4. Wait for done
for i in range(20):
    time.sleep(3)
    st = manager_status(tab, user_id)
    if st.get('state') in ('done', 'failed'):
        break
print('manager:', st)
time.sleep(6)

# 5. Navigate to API keys
step('nav api keys', lambda: cf_post(f'/tabs/{tab}/navigate', {'userId': user_id, 'url': f'{PROXY_BASE}/dashboard/api-keys'}))
time.sleep(8)
print('api-keys body:', evaluate(tab, user_id, 'document.body.innerText.slice(0,300)').get('result', '')[:250])

# 6. Click + New key
step('click new key', lambda: cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('New key')"}))
time.sleep(4)

# 7. Fill label
fill = evaluate(tab, user_id, '''(function(){
  var inputs = Array.prototype.slice.call(document.querySelectorAll('input'));
  var target = null;
  for (var i=0;i<inputs.length;i++){
    var ph = inputs[i].placeholder || '';
    var nm = inputs[i].name || '';
    if (/label|name/i.test(ph) || /label/i.test(nm)) { target = inputs[i]; break; }
  }
  if (!target) target = inputs[0];
  if (!target) return JSON.stringify({err:'no_input'});
  var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(target, 'farm9router');
  target.dispatchEvent(new Event('input',{bubbles:true}));
  target.dispatchEvent(new Event('change',{bubbles:true}));
  return JSON.stringify({filled:true,val:target.value});
})()''').get('result', '')
print('fill:', fill)

# 8. Click Create key (the one in the dialog)
step('click create key', lambda: cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Create key')"}))
time.sleep(6)

# 9. Harvest key — look for sk- / th_ / key-like values
harvest = evaluate(tab, user_id, '''(function(){
  var patterns =[/th_[A-Za-z0-9_\\-]{10,}/g, /sk-[A-Za-z0-9_\\-]{10,}/g, /[a-zA-Z0-9]{30,}/g];
  var found = [];
  var txt = document.body.innerText + ' ' + document.body.innerHTML;
  for (var i=0;i<patterns.length;i++){
    var m = txt.match(patterns[i]);
    if (m) found = found.concat(m);
  }
  var unique = Array.from(new Set(found)).slice(0,10);
  var codes = Array.prototype.slice.call(document.querySelectorAll('code,pre')).map(function(c){return (c.textContent||'').trim()}).filter(function(s){return s.length>10}).slice(0,5);
  return JSON.stringify({found:unique, codes:codes});
})()''').get('result', '{}')
print('harvest:', harvest)

# Save creds
with open('D:/tokenharbor-farmer/accounts.json', 'a') as f:
    f.write(json.dumps({'email': email, 'password': pw, 'harvest': harvest, 'ts': time.time()}) + '\n')
print('saved to accounts.json')