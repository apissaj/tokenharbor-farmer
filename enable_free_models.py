"""
enable_free_models.py — Login ke akun TokenHarbor, enable free models consent,
lalu test API key.
Usage: python enable_free_models.py <email> <password> <apikey>
"""
import sys, json, time, uuid, urllib.request

sys.path.insert(0, 'D:/tokenharbor-farmer')
from submit_manager_runner import evaluate, cf_post, CAMOFOX, PROXY_BASE

email, password, apikey = sys.argv[1], sys.argv[2], sys.argv[3]
user_id = f'th_{uuid.uuid4().hex[:8]}'

# 1. Open login page
r = urllib.request.urlopen(urllib.request.Request(
    f'{CAMOFOX}/tabs',
    data=json.dumps({'userId': user_id, 'sessionKey': user_id,
                     'url': f'{PROXY_BASE}/login'}).encode(),
    headers={'Content-Type': 'application/json'}), timeout=60)
tab = json.loads(r.read().decode())['tabId']
print('tab:', tab)
time.sleep(6)

cf_post(f'/tabs/{tab}/click', {'userId': user_id, 'selector': "button:has-text('Essential only')"})
time.sleep(1)

# 2. Fill login form
fill = evaluate(tab, user_id, """(function(){
  var e=document.querySelector('input[name=email]');
  var p=document.querySelector('input[name=password]');
  if(!e||!p) return JSON.stringify({err:'no_fields',hasE:!!e,hasP:!!p});
  var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  setter.call(e, %s); e.dispatchEvent(new Event('input',{bubbles:true}));
  setter.call(p, %s); p.dispatchEvent(new Event('input',{bubbles:true}));
  return JSON.stringify({ok:true});
})()""" % (json.dumps(email), json.dumps(password))).get('result','')
print('fill:', fill)

# 3. Submit login
sub = evaluate(tab, user_id, """(function(){
  var f=document.querySelector('form');
  var b=Array.prototype.slice.call(document.querySelectorAll('button')).find(function(x){return /^sign in$/i.test((x.textContent||'').trim())});
  if(b){b.click();return 'clicked_btn';}
  if(f&&f.requestSubmit){f.requestSubmit();return 'requestSubmit';}
  return 'nf';
})()""").get('result','')
print('submit:', sub)
time.sleep(8)

body = evaluate(tab, user_id, 'document.body.innerText.slice(0,400)').get('result','')
print('after login:', body[:250])

# 4. Look for "Enable free models" dialog and accept
enable = evaluate(tab, user_id, """(function(){
  var btns=Array.prototype.slice.call(document.querySelectorAll('button'));
  var b=btns.find(function(x){return /turn on|enable|accept|got it|sure/i.test(x.textContent||'')});
  if(b){var t=b.textContent.trim();b.click();return 'clicked:'+t;}
  return 'no_dialog';
})()""").get('result','')
print('free-models dialog:', enable)
time.sleep(5)

# 5. If not found on dashboard, go to privacy settings
state = evaluate(tab, user_id, """(function(){
  return JSON.stringify({url:location.href, body:document.body.innerText.slice(0,300)});
})()""").get('result','')
print('state:', state[:400])
