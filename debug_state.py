import sys, json, time, urllib.request
sys.path.insert(0, 'D:/tokenharbor-farmer')
from submit_manager_runner import evaluate, cf_post, PROXY_BASE

# Get current tab
tabs = json.loads(urllib.request.urlopen('http://localhost:9377/tabs').read().decode())
tab = tabs['tabs'][0]['tabId']
uid = tabs['tabs'][0].get('userId')
print('tab', tab, 'uid', uid)

# Check current URL + form state
state = evaluate(tab, uid, '''(function(){
  return JSON.stringify({
    url: location.href,
    hasForm: !!document.querySelector('form'),
    hasEmail: !!document.querySelector('input[name=email]'),
    hasPw: !!document.querySelector('input[name=password]'),
    hasTurnstile: !!document.querySelector('input[name=cf-turnstile-response]'),
    sm: window.__submitManager ? window.__submitManager.status() : 'none',
    bodyHead: document.body.innerText.slice(0,300)
  });
})()''').get('result','')
print('STATE:', state)