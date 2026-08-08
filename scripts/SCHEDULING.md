# Auto-generate the dashboard daily (macOS launchd)

This runs the full CMC pipeline — whose last stage writes
`data/dashboard/dashboard_<date>.html` — **every weekday at 7:00 AM** on your Mac.

The schedule uses **launchd** (macOS's native scheduler). Your Mac must be
powered on at 7:00 AM; if it's asleep, launchd runs the job when it next wakes.
If it's fully shut down, that day is skipped.

## Files
- `scripts/run_daily.sh` — runs the pipeline + screenshot, logs to `data/logs/run_<date>.log`.
- `scripts/com.cmc.dashboard.plist` — the schedule (weekdays 07:00).
- `scripts/screenshot_dashboard.py` — captures a PNG of the fresh dashboard.

## Daily screenshot + email — one-time setup

Each run saves an image of the dashboard to
`data/dashboard/shots/dashboard_<date>.png` **and emails it to you** (inline +
attached), reusing the same Gmail App Password the brief already uses
(`config/secrets.yaml`: `gmail_app_password` / `gmail_sender` / `gmail_recipient`,
currently → `fan2010.wu@gmail.com`). No new credentials needed. If the App Password
isn't set, it just saves the file and skips the email.

Because the dashboard is a WebGL page (the globe), it's captured with a real
headless browser (Playwright). Install it once, **with the project venv active**:

```bash
source "/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat/.venv/bin/activate"
pip install playwright
playwright install chromium
```

Test the capture **and email** by hand (after a dashboard exists):

```bash
python "/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat/scripts/screenshot_dashboard.py"
# → saves the PNG and emails it to fan2010.wu@gmail.com; check your inbox
open "/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat/data/dashboard/shots/"
```

The screenshot step is **non-fatal**: if it ever fails, the pipeline and dashboard
still complete — you just won't get that day's image. (If the globe ever comes out
blank in the image, tell me and I'll lengthen the render wait or switch the capture
to your installed Chrome.)

## Install (copy-paste into Terminal, once)

```bash
PROJ="/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat"

# 1. make the runner executable
chmod +x "$PROJ/scripts/run_daily.sh"

# 2. copy the schedule into your LaunchAgents folder
cp "$PROJ/scripts/com.cmc.dashboard.plist" ~/Library/LaunchAgents/

# 3. load it (modern syntax; the 2nd line is a fallback for older macOS)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cmc.dashboard.plist \
  || launchctl load -w ~/Library/LaunchAgents/com.cmc.dashboard.plist
```

That's it — it will now run automatically each weekday at 7:00 AM.

## Test it right now (don't wait for 7 AM)

```bash
# Run the exact job launchd will run, immediately:
launchctl start com.cmc.dashboard

# ...or run the script directly and watch the log:
bash "$PROJ/scripts/run_daily.sh"
tail -f "$PROJ/data/logs/run_$(date +%Y-%m-%d).log"
```

A successful run ends with a "CMC Run Summary" box and a fresh
`data/dashboard/dashboard_<today>.html`.

## Check status / logs

```bash
launchctl list | grep com.cmc.dashboard        # is it loaded?
tail -n 40 "$PROJ/data/logs/run_$(date +%Y-%m-%d).log"   # today's run log
```

## Change the time

Edit `~/Library/LaunchAgents/com.cmc.dashboard.plist` (change the `Hour`/`Minute`
values), then reload:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.cmc.dashboard.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.cmc.dashboard.plist
```

## Uninstall

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.cmc.dashboard.plist \
  || launchctl unload ~/Library/LaunchAgents/com.cmc.dashboard.plist
rm ~/Library/LaunchAgents/com.cmc.dashboard.plist
```

## Notes
- **API keys / network:** the run uses `config/secrets.yaml` and live Yahoo/FRED
  access — it must run on your Mac, not in a cloud/Cowork session.
- **First launch permission:** macOS may prompt to allow Terminal/bash to run in
  the background the first time — approve it.
- **Weekends:** intentionally skipped (markets closed). To include them, add
  `Weekday 6` and `Weekday 0` (or `7`) blocks to the plist.
- **It only generates data + files** — nothing is traded. Consistent with the
  system's "no live trades approved" stance.
