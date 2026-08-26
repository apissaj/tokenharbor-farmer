/*
 * submit-manager.js
 * ---------------------------------------------------------------------------
 * In-page submit manager for TokenHarbor signup (and any Cloudflare Turnstile
 * gated Next.js Server-Action form).
 *
 * What it does:
 *   - Polls `input[name=cf-turnstile-response]` until it is populated (Turnstile
 *     solved / token injected).
 *   - Then waits for the email + password fields to exist (TokenHarbor renders
 *     them only AFTER the Turnstile callback fires — a 2-phase form), so this
 *     manager tolerates fields appearing either before OR after the token.
 *   - Optionally auto-fills email/password, then triggers a NATIVE form submit
 *     via form.requestSubmit() so the Next.js Server Action (multipart/form-data
 *     POST) fires exactly as a real browser would — no brittle hand-built body.
 *
 * How to inject (Camoufox REST API):
 *   POST /tabs/:tabId/evaluate
 *   { "userId": "...", "expression": "<entire contents of this file>" }
 *
 *   // then either:
 *   POST /tabs/:tabId/evaluate  { "userId":"...",
 *     "expression": "window.__submitManager.start({email:'a@b.com', password:'x'})" }
 *
 *   // or pre-seed config before injecting:
 *   window.__submitManagerConfig = { email, password, autoFill:true };
 *   (start() auto-runs if __submitManagerConfig is present at load time)
 *
 * Read status any time:
 *   evaluate: "JSON.stringify(window.__submitManager.status())"
 *   The log buffer is also at window.__submitManager.log (array of {t,ev,data}).
 * ---------------------------------------------------------------------------
 */
(function () {
  'use strict';

  // Idempotent: don't clobber a running instance.
  if (window.__submitManager && window.__submitManager.__loaded) {
    console.log('[submitManager] already loaded; use .start() to (re)configure.');
    return;
  }

  var SM = {
    __loaded: true,
    config: {
      email: '',
      password: '',
      autoFill: true,        // fill email/password before submitting
      requireSubmitButton: false, // if true, wait for a visible submit button
      submitDelayMs: 0,      // small pause after fields ready (human-like)
      maxWaitMs: 180000,     // give up after this long (3 min)
      pollMs: 150            // poll cadence
    },
    state: 'idle',           // idle | watching | submitting | done | failed | stopped
    log: [],
    _timer: null,

    start: function (cfg) {
      if (cfg) Object.assign(this.config, cfg);
      this.log = [];
      this.state = 'watching';
      this._log('start', this.config);
      this._watch();
      return 'watching';
    },

    stop: function () {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
      this.state = 'stopped';
      this._log('stopped');
    },

    // Manual trigger (e.g. after you fill fields yourself).
    submitNow: function () {
      var f = this._getForm();
      if (f) this._submit(f);
      else this._log('submitNow:no_form');
    },

    status: function () {
      return {
        state: this.state,
        tokenLen: (this._getToken() || '').length,
        hasForm: !!this._getForm(),
        hasEmail: !!this._getField('email'),
        hasPassword: !!this._getField('password'),
        recent: this.log.slice(-12)
      };
    },

    _log: function (ev, data) {
      try { this.log.push({ t: Date.now(), ev: ev, data: data === undefined ? null : data }); } catch (e) {}
      try { console.log('[submitManager]', ev, data === undefined ? '' : data); } catch (e) {}
    },

    _getForm: function () {
      var tok = document.querySelector('input[name=cf-turnstile-response]');
      if (tok && tok.form) return tok.form;
      return document.querySelector('form') || null;
    },

    _getToken: function () {
      var t = document.querySelector('input[name=cf-turnstile-response]');
      return t ? (t.value || '') : '';
    },

    _getField: function (name) {
      return document.querySelector(
        'input[name="' + name + '"], input#'+name+
        ', input[autocomplete="'+name+'"], input[type="'+name+'"]'
      ) || null;
    },

    _fill: function () {
      var ok = true, did = { email: false, password: false };
      if (this.config.email) {
        var e = this._getField('email');
        if (e) {
          e.focus();
          e.value = this.config.email;
          e.dispatchEvent(new Event('input', { bubbles: true }));
          e.dispatchEvent(new Event('change', { bubbles: true }));
          e.blur();
          did.email = true;
        } else ok = false;
      }
      if (this.config.password) {
        var p = this._getField('password');
        if (p) {
          p.focus();
          p.value = this.config.password;
          p.dispatchEvent(new Event('input', { bubbles: true }));
          p.dispatchEvent(new Event('change', { bubbles: true }));
          p.blur();
          did.password = true;
        } else ok = false;
      }
      this._log('filled', did);
      return ok;
    },

    _findSubmitButton: function (form) {
      if (!form) return null;
      var btns = form.querySelectorAll('button[type=submit], button:not([type]), input[type=submit]');
      for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        if (b.offsetParent !== null && !b.disabled) return b; // visible & enabled
      }
      // fall back to any button whose text looks like submit
      var all = form.querySelectorAll('button');
      for (var j = 0; j < all.length; j++) {
        var t = (all[j].textContent || '').toLowerCase();
        if (/sign up|create|continue|submit|register/.test(t)) return all[j];
      }
      return null;
    },

    _watch: function () {
      var self = this;
      var deadline = Date.now() + this.config.maxWaitMs;
      this._timer = setInterval(function () {
        try {
          var form = self._getForm();
          if (!form) {
            if (Date.now() > deadline) self._fail('no_form');
            return;
          }
          var val = self._getToken();
          if (!val) {
            // No Turnstile token field at all → captcha not required. If the
            // email/password fields are present, submit directly.
            var noTokenField = !document.querySelector('input[name=cf-turnstile-response]');
            var fReady = form && self._getField('email') && self._getField('password');
            if (noTokenField && fReady && self.config.autoFill) {
              self._log('no_captcha_direct_submit');
              self._fill();
              self._submit(form);
              return;
            }
            if (Date.now() > deadline) self._fail('token_timeout');
            return; // token not populated yet — keep waiting
          }
          self._log('token_present', { len: val.length });

          // 2-phase form: email/password may appear only after the Turnstile
          // callback. If we need them and they aren't here yet, keep waiting.
          var needFill = self.config.autoFill && (self.config.email || self.config.password);
          var emailMissing = needFill && self.config.email && !self._getField('email');
          var pwMissing = needFill && self.config.password && !self._getField('password');
          var btnMissing = self.config.requireSubmitButton && !self._findSubmitButton(form);

          if (emailMissing || pwMissing || btnMissing) {
            self._log('waiting_for_more', { emailMissing: !!emailMissing, pwMissing: !!pwMissing, btnMissing: !!btnMissing });
            if (Date.now() > deadline) self._fail('fields_timeout');
            return;
          }

          if (needFill) self._fill();
          self._submit(form);
        } catch (err) {
          self._log('error', String(err && err.message ? err.message : err));
        }
      }, this.config.pollMs);
    },

    _submit: function (form) {
      if (this.state === 'submitting' || this.state === 'done') return;
      this.state = 'submitting';
      this._log('submitting');
      if (this._timer) { clearInterval(this._timer); this._timer = null; }

      var self = this;
      var doSubmit = function () {
        try {
          // Prefer a real submit button click if gating logic lives on it.
          var btn = self._findSubmitButton(form);
          if (btn) {
            btn.click();
            self._log('clicked_submit_button');
          } else if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
            self._log('requestSubmit_called');
          } else {
            form.submit();
            self._log('form_submit_called');
          }
        } catch (err) {
          self._log('submit_error', String(err && err.message ? err.message : err));
        }
        setTimeout(function () {
          self.state = 'done';
          self._log('done');
        }, 600);
      };

      if (this.config.submitDelayMs > 0) setTimeout(doSubmit, this.config.submitDelayMs);
      else doSubmit();
    },

    _fail: function (reason) {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
      this.state = 'failed';
      this._log('failed', reason);
    }
  };

  window.__submitManager = SM;

  // Auto-start if a config was seeded before injection.
  if (window.__submitManagerConfig) {
    SM.start(window.__submitManagerConfig);
  } else {
    console.log('[submitManager] loaded. Call window.__submitManager.start({email,password}).');
  }
})();
