# Chief Market Cat — Setup Guide

Get CMC running in about 15 minutes with three free API keys.

---

## Step 1 — Install Python dependencies

```bash
cd chief-market-cat
pip install -e ".[dev]"
```

> **Note:** This installs the MVP 1 runtime dependencies from `pyproject.toml`,
> including yfinance, requests, PyYAML, and the official Google Gemini SDK.

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

To set up the cron job:
```bash
crontab -e
# Add this line:
0 10 * * * cd /path/to/chief-market-cat && python -m cmc.run >> data/logs/cron.log 2>&1
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: yfinance` | `pip install yfinance` |
| `ModuleNotFoundError: google.generativeai` | `pip install google-generativeai` |
| Brief saved but no email | Check Gmail App Password is filled in (not a placeholder) |
| No signals classified | Check `gemini_key` in secrets.yaml is a real key |
| No news items | Check `newsapi_key` in secrets.yaml is a real key |
| No macro data | Check `fred_key` in secrets.yaml is a real key |
| ASX prices missing | yfinance uses `.AX` suffix — symbols like `CBA.AX` are correct |
