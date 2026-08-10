# Chief Market Cat — Setup Guide

Get CMC running in about 15 minutes with three free API keys.

---

## Step 1 — Install Python dependencies

**Python 3.11+ required.** The system Python on macOS is often 3.10 or older — too old. Check first:

```bash
python3 --version
```

If it's below 3.11, use `python3.13` (or whichever 3.11+ you have installed via Homebrew or python.org):

```bash
cd chief-market-cat
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

All subsequent commands in this guide assume the venv is active. To reactivate in a new terminal:

```bash
source .venv/bin/activate
```

Or run without activating by calling `.venv/bin/python -m cmc.run` directly.

> **Gemini SDK note:** `pyproject.toml` pins `google-generativeai`, which Google has deprecated in favour of `google-genai`. The old SDK still works for MVP 1 — migration to `google-genai` is a later task.

✅ **Step 1 done when:** `pip install -e ".[dev]"` completes and `python -c "import yfinance, google.generativeai, yaml, requests"` raises no errors.

---

## Step 2 — Get your 3 free API keys

### A. NewsAPI (news headlines)
1. Go to [newsapi.org](https://newsapi.org)
2. Click **Get API Key** → sign up with email
3. Your key appears on the dashboard immediately (free tier: 100 req/day)

### B. FRED (macroeconomic data — US Treasury yield, Fed Funds, VIX)
1. Go to [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)
2. Register for a free account → **My Account → API Keys → Request API Key**
3. Key arrives by email within minutes

### C. Gemini API (AI signal classification + daily brief)
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with your Google account
3. Click **Get API Key → Create API Key**
4. Free tier includes ~1 million tokens/day on `gemini-1.5-flash` — more than enough for daily CMC runs

---

## Step 3 — Set up Gmail App Password (for email delivery)

This lets CMC email the daily brief to your Gmail inbox without using your main password.

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. **Security → 2-Step Verification** — enable it if not already on
3. Back in Security → scroll to **App Passwords**
4. Select app: **Mail** → device: **Other** → type "CMC" → click **Generate**
5. Copy the 16-character password shown (you won't see it again)

> You can skip this step if you don't want email delivery — CMC will still save briefs to `data/briefs/`.

---

## Step 4 — Fill in `config/secrets.yaml`

Open `config/secrets.yaml` and replace each placeholder:

```yaml
newsapi_key: YOUR_NEWSAPI_KEY_HERE      ← paste NewsAPI key
fred_key: YOUR_FRED_KEY_HERE            ← paste FRED key
gemini_key: YOUR_GEMINI_API_KEY_HERE    ← paste Gemini key
gmail_app_password: YOUR_GMAIL_APP_PASSWORD_HERE  ← paste App Password (or leave placeholder to skip email)
gmail_sender: fan2010.wu@gmail.com      ← your Gmail address
gmail_recipient: fan2010.wu@gmail.com   ← where to send the brief
```

> `config/secrets.yaml` is in `.gitignore` — it will never be committed to git.

---

## Step 5 — Run CMC

```bash
cd chief-market-cat
source .venv/bin/activate   # if not already active
python -m cmc.run
```

This will:
1. Fetch price data for all 16 watchlist symbols (US + ASX) via yfinance
2. Fetch top 20 business headlines from NewsAPI
3. Fetch US 10Y yield, Fed Funds rate, and VIX from FRED
4. Classify each signal using Gemini (`gemini-1.5-flash`)
5. Run 6 verification checks + 5 risk gate rules
6. Write a daily brief to `data/briefs/YYYY-MM-DD.md`
7. Email the brief to your Gmail
8. Log the run summary for review

> MVP 1 is monitoring and decision support only. The default run does not place
> live broker orders and does not automatically log paper trades.

---

## Optional — Alpaca paper trading broker

If you want CMC to connect to an Alpaca paper account (for portfolio state):

1. Sign up free at [alpaca.markets](https://alpaca.markets)
2. Go to **Paper Trading → API Keys → Generate**
3. Add both keys to `config/secrets.yaml`
4. Enable the broker source in `config/sources.yaml` (`alpaca_paper: enabled: true`)

---

## Optional — LangSmith tracing

Records one redacted run per classified signal so classifier behaviour can be
reviewed over time. Off unless you switch it on. No secrets, prompts, headlines,
article bodies, or rationale text are exported — see
`docs/adr/0001-langsmith-tracing-boundary.md` for the exact field list.

```bash
.venv/bin/pip install -e '.[tracing]'

cp config/langsmith.env.example config/langsmith.env
chmod 600 config/langsmith.env
$EDITOR config/langsmith.env      # paste your key from smith.langchain.com
```

`scripts/run_daily.sh` sources that file, so the scheduled run traces without a
plist change. For interactive shells add to `~/.zshrc` (not `~/.zshenv` — the
launchd job runs under bash and reads neither):

```bash
[ -f "<project>/config/langsmith.env" ] && . "<project>/config/langsmith.env"
```

Check it before trusting a live run — this sends nothing, it just prints the
payload that would be transmitted:

```bash
.venv/bin/python scripts/trace_one_classification.py
```

Disable: `CMC_LANGSMITH_TRACING=0` for one run, or delete `config/langsmith.env`.

If traces don't appear, check the run log. Every run states
`classify_signal: langsmith tracing enabled|disabled`, and the first export
failure logs a warning with the HTTP status — a rejected key shows up as
`export failed (HTTPError, HTTP 403)`. Export failures never affect
classification, so without those lines a bad key would be invisible.

Never put the key in `scripts/com.cmc.dashboard.plist` — that file is tracked in
git.

---

## Watchlist

CMC monitors 16 symbols by default:

| Market | Symbols |
|--------|---------|
| US | AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, SPY, QQQ, GLD |
| ASX | CBA.AX, BHP.AX, RIO.AX, WBC.AX, ANZ.AX, NAB.AX |

Edit `config/sources.yaml` → `watchlist` to add or remove symbols.

---

## Schedule (automatic daily runs)

CMC is configured to run at **10:00 AM Sydney time** (AEST/AEDT), which catches:
- US market close recap (prior day fully settled)
- ASX open intelligence (right as the market opens)

To set up the cron job (use the venv Python, not system Python):
```bash
crontab -e
# Add this line (replace /path/to with your actual path):
0 10 * * * cd /path/to/chief-market-cat && .venv/bin/python -m cmc.run >> data/logs/cron.log 2>&1
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python3 --version` shows < 3.11 | Install Python 3.13 via [python.org](https://www.python.org/downloads/) or `brew install python@3.13`, then recreate the venv with `python3.13 -m venv .venv` |
| `ModuleNotFoundError` after activating venv | Venv may not be active — run `source .venv/bin/activate` first |
| `ModuleNotFoundError: yfinance` | `pip install -e ".[dev]"` inside the activated venv |
| `ModuleNotFoundError: google.generativeai` | `pip install google-generativeai` inside venv |
| `DeprecationWarning: google-generativeai` | Expected for MVP 1 — migration to `google-genai` is a later task |
| Brief saved but no email | Check Gmail App Password is filled in (not a placeholder) |
| No signals classified | Check `gemini_key` in secrets.yaml is a real key |
| No news items | Check `newsapi_key` in secrets.yaml is a real key |
| No macro data | Check `fred_key` in secrets.yaml is a real key |
| ASX prices missing | yfinance uses `.AX` suffix — symbols like `CBA.AX` are correct |
| Cron job does nothing | Use full path to venv Python: `/path/to/chief-market-cat/.venv/bin/python` |
