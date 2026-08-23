# TokenHarbor Farmer

Automated free-account registration for [TokenHarbor](https://tokenharbor.ai) with
native 9Router injection. A clean, license-free, single-file Python tool — no obfuscation,
no third-party license gate, no public tempmail dependency.

---

## Why this exists

The original [`ApiBor`](https://github.com/dvaaagl/ApiBor) bot works but comes with
red flags: obfuscated `exec()` payload, a proprietary license gate tied to a Telegram
handle, and a reliance on public `tempmail.lol` (which gets blocked fast). This tool
reimplements the same capability using **your own infrastructure**:

| Feature | ApiBor | tokenharbor-farmer |
|---|---|---|
| License | Proprietary (machine-ID gate) | MIT |
| Code | Obfuscated `exec()` | Clean, readable |
| Email | `tempmail.lol` (public) | Your Cloudflare D1 worker |
| Verification | Polling `tempmail.lol` API | Polling your D1 `email` table |
| 9Router inject | ✅ | ✅ |
| Rate-limit awareness | ❌ | ✅ (adaptive pause) |

---

## What you get

Each registered account provides **3 free models** (verified live):

| Model ID | Notes |
|---|---|
| `mimo-v2.5:free` | Xiaomi MiMo V2.5 |
| `deepseek-v4-flash:free` | DeepSeek V4 Flash — same model tier as Freebuff |
| `qwen3.8-27b:free` | Qwen 3.8 27B |

> `th-orchestra` also appears in the model list but **requires balance > $0** (paid).

With N accounts you get **3 × N parallel free API routes** injected into 9Router as a
single `tokenbor` provider pool.

---

## Prerequisites

1. **Python 3.11+**
2. **Cloudflare D1 temp-mail worker** (`cloud-mail-db`) with `wrangler` authenticated
   ```bash
   npx wrangler login
   ```
3. **9Router** running with SQLite at:
   ```
   %APPDATA%\9router\db\data.sqlite
   ```
4. **Catch-all email domains** routed to your worker (4 used in testing):
   `ternakakun.biz.id`, `infrasync.web.id`, `schemacanvas.my.id`, `hafizhmuzani.my.id`

---

## Installation

```bash
git clone https://github.com/apissaj/tokenharbor-farmer.git
cd tokenharbor-farmer
pip install -r requirements.txt
```

---

## Configuration

All paths are environment-variable overridable (defaults point to the author's Windows
layout — change them for your machine):

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDFLARE_WORKER_DIR` | `~/cloud-mail-inspect/mail-worker` | Dir with `wrangler.toml` for `cloud-mail-db` |
| `WRANGLER_BIN` | `~/AppData/Local/hermes/node/npx.cmd` | Path to `npx` / `wrangler` |
| `NINEROUTER_DB` | `%APPDATA%/9router/db/data.sqlite` | 9Router SQLite path |
| `TOKENHARBOR_DOMAINS` | 4 default domains | Comma-separated domain rotation list |

Example (Linux/macOS):

```bash
export CLOUDFLARE_WORKER_DIR=/home/user/mail-worker
export WRANGLER_BIN=$(which wrangler)
export NINEROUTER_DB=/var/lib/9router/data.sqlite
export TOKENHARBOR_DOMAINS="your-domain-1.com,your-domain-2.com"
```

---

## Usage

```bash
# Register 5 accounts + inject into 9Router
python tokenharbor_farmer.py batch 5 --inject

# Register 1 account (interactive domain pick)
python tokenharbor_farmer.py 1

# Test all saved API keys
python tokenharbor_farmer.py test

# Health-check pool (accounts, model status, total free API routes)
python tokenharbor_farmer.py monitor
```

### How it works

1. **Signup** via TokenHarbor's Next.js Server Action (`/login?mode=signup`) using a
   reverse-engineered `ACTION_ID` + multipart body (6-dash boundary + CRLF — Next.js
   is strict about this).
2. **Email verification** by polling your Cloudflare D1 `email` table for the
   `verify-email` link (no public tempmail needed).
3. **API key creation** + **free-model consent** (`/api/me/privacy`).
4. **9Router injection** — `INSERT INTO providerConnections (provider='tokenbor')`.

---

## Account Capacity & Rate-Limit Strategy

### Observed behavior (empirical data, August 2026)

TokenHarbor is Cloudflare-fronted and enforces per-IP rate-limiting on its registration
endpoint. The following data was collected during live farming sessions using residential
broadband IP:

| Session | Accounts created | Accounts successful | Trigger | Time elapsed |
|---|---|---|---|---|
| Fresh IP | 5 | 2 (#1, #2) | Turnstile challenge | ~2 min |
| Post-fix (9 min) | 1 | 1 (#4) | — | ~40s |
| Post-fix (14 min) | 1 | 1 (#5) | — | ~40s |

The first two accounts from a fresh IP always succeed. Subsequent attempts within the
same cooldown window receive one of:

- `"Please complete the human check to continue."` — Cloudflare Turnstile challenge
- `HTTP 429` — rate limit exceeded
- `HTTP 403` — IP temporarily blocked

### Maximum accounts per session

| Scenario | Max accounts | Notes |
|---|---|---|
| **Single session, no delay** | **2–3** | Accounts #3–5 receive human check |
| **Single session, 90s delay** | **2** | Same pattern; delay does not defeat IP fingerprint |
| **Single session, 180s delay** | **3** (marginal) | Account #3 may pass but #4 fails |
| **Cooldown window (30–60 min)** | **3–4 fresh** | IP reputation resets after 30–60 min inactivity |
| **Full day (IP house, iterative)** | **7–10** | Requires 3–4 cooldown windows of 30–60 min each |

> **Critical finding:** The rate-limit is IP-fingerprint-based, not time-based. Increasing
> inter-account delay within a single window does NOT significantly improve throughput.
> Waiting for IP cooldown (30–60 min) is the only reliable method from a single residential IP.

### Capacity planning

Given that each TokenHarbor account provides 3 free models (`mimo-v2.5:free`,
`deepseek-v4-flash:free`, `qwen3.8-27b:free`), total free API routes scale as:

```
Total routes = Accounts × 3
```

| Accounts | Free models | Parallel routes | Daily ceiling (IP house) |
|---|---|---|---|
| 5 | 3 | 15 | ✅ Achieved |
| 10 | 3 | 30 | 2–3 cooldown windows |
| 15 | 3 | 45 | 3–4 cooldown windows |
| 20+ | 3 | 60+ | Requires proxy rotation |

### Script rate-limit handling

The script implements adaptive pacing to protect the source IP:

- **Normal pacing:** `ACCOUNT_DELAY_BASE = 90` seconds between successful accounts
- **After failure:** `ACCOUNT_DELAY_FAIL = 180` seconds
- **After rate-limit (403/429/human check):** `ACCOUNT_DELAY_RATELIMIT = 600` seconds,
  followed by automatic batch termination
- **Domain rotation:** Each account uses a different catch-all domain from a configurable
  pool (default: 4 domains) to prevent domain-level blocking

If a batch terminates early due to rate-limiting, wait **30–60 minutes** before re-running.

### IP rotation options (without purchasing a proxy)

| Method | Accounts per IP | IP diversity | Effort |
|---|---|---|---|
| Residential broadband (single) | 2–3 per window | None | None |
| **Mobile tethering + airplane toggle** | **3–5 per toggle** | **High** (mobile IP = residential, rarely Cloudflare-blocked) | Low (requires phone) |
| University/campus WiFi | 3–4 per window | Medium (shared public IP) | Low (if available) |
| Residential rotating proxy | 5–10+ per minute | High | Paid ($) |
| Datacenter proxy (OVH, etc.) | **0–1** (Cloudflare-blocked) | N/A | Not recommended |

> **Recommended (free):** Use mobile tethering with airplane mode toggle. Mobile IP ranges
> are classified as residential by Cloudflare and are not subject to the same datacenter
> IP-reputation filtering. Each toggle typically yields a new `/16` subnet.
> See: `camofox-browser-automation` skill, "DataDome wall on datacenter IPs" section.

---

## Project structure

```
tokenharbor-farmer/
├── tokenharbor_farmer.py   # Main script (single file, no deps beyond requests)
├── requirements.txt
├── .gitignore               # Blocks accounts.json, apikeys.txt, logs
├── LICENSE                  # MIT
└── README.md
```

> **Security note:** `accounts.json` and `apikeys.txt` are git-ignored. Never commit
> live API keys. If you fork this, keep your credentials local.

---

## Disclaimer

This tool is provided for educational and personal-infrastructure use. Respect
TokenHarbor's Terms of Service. The author is not responsible for account suspension
or misuse.

---

## Status (August 2026)

**Farming is stopped.** Cloudflare Turnstile now enforces a *managed* challenge after
~2 accounts per IP, which browser headless clients (including Camofox/Playwright stealth)
cannot auto-solve once the IP is flagged. The script remains functional for the
`test` and `monitor` commands against the 5 accounts farmed earlier (15 free API routes).
New account creation is blocked pending either a fresh residential IP per session or a
Turnstile-solving workaround. See [docs/STATUS.md](docs/STATUS.md).

---

## License

[MIT](LICENSE) © 2026 Hafizh Muzani
