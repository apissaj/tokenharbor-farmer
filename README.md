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

# List tokenbor entries in 9Router
python tokenharbor_farmer.py 9router
```

### How it works

1. **Signup** via TokenHarbor's Next.js Server Action (`/login?mode=signup`) using a
   reverse-engineered `ACTION_ID` + multipart body (6-dash boundary + CRLF — Next.js
   is strict about this).
2. **Email verification** by polling your Cloudflare D1 `email` table for the
   `verify-email` link (no public tempmail needed).
3. **API key creation** + **free-model consent** (`/api/me/privacy`).
4. **9Router injection** — `INSERT INTO providerConnections (provider='tokenbor')`.

### Rate-limit handling

TokenHarbor (Cloudflare-fronted) starts challenging requests after ~2 accounts from the
same IP. The script:

- Spaces accounts **90s apart** (180s after a failure)
- **Auto-stops** the batch on `403` / `429` / "human check" to protect your IP
- Domain-rotates every account

If you hit a block, wait 30–60 min for IP cooldown, then re-run.

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

## License

[MIT](LICENSE) © 2026 Hafizh Muzani
