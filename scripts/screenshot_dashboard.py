#!/usr/bin/env python3
"""Screenshot the latest CMC dashboard, save it, and email it to you.

The dashboard is a WebGL page (globe.gl), so a plain HTML-to-image tool won't do —
we render it in a headless browser, wait for the globe + arcs to draw, then capture
to data/dashboard/shots/dashboard_<date>.png. The PNG is then emailed (inline +
attached) using the SAME Gmail App Password the brief already uses (config/secrets.yaml:
gmail_app_password / gmail_sender / gmail_recipient).

One-time setup (in the project venv):
    pip install playwright
    playwright install chromium

Called automatically by scripts/run_daily.sh after the pipeline builds the HTML.
Run by hand anytime:  python scripts/screenshot_dashboard.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

PROJ = Path("/Users/wulingsenmacpro/Codex/Vibe trading/chief-market-cat")
DASH_DIR = PROJ / "data" / "dashboard"
SHOT_DIR = DASH_DIR / "shots"
sys.path.insert(0, str(PROJ))  # so `import cmc.config` works when run as a file

# Big, retina-crisp capture. deviceScaleFactor=2 → sharp text on the panels.
VIEWPORT = {"width": 1680, "height": 1050}
SCALE = 2
RENDER_WAIT_MS = 6000   # let the globe spin up + arcs animate before the shot


def email_screenshot(png: Path) -> bool:
    """Email the screenshot (inline + attached) via Gmail SMTP, reusing the
    brief's credentials. Non-fatal: returns False and logs if it can't send."""
    import ssl
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.image import MIMEImage

    try:
        from cmc.config import load_config, is_placeholder
    except Exception as e:  # noqa: BLE001
        print("screenshot/email: cannot load config —", e)
        return False

    secrets = load_config().get("secrets", {})
    password = secrets.get("gmail_app_password", "")
    sender = secrets.get("gmail_sender", "fan2010.wu@gmail.com")
    recipient = secrets.get("gmail_recipient", "fan2010.wu@gmail.com")
    if not password or is_placeholder(password):
        print("screenshot/email: Gmail App Password not configured — skipping email")
        return False

    date = png.stem.replace("dashboard_", "")
    msg = MIMEMultipart("related")
    msg["Subject"] = f"CMC Dashboard — {date}"
    msg["From"] = sender
    msg["To"] = recipient

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(
        f"CMC dashboard for {date} attached.\n"
        "Supervised intelligence tool — no live trades approved.", "plain", "utf-8"))
    alt.attach(MIMEText(
        f"<html><body style='font-family:sans-serif;background:#07090f;color:#dde7ff;padding:12px'>"
        f"<p>CMC dashboard — <b>{date}</b></p>"
        f"<img src='cid:shot' style='max-width:100%;border-radius:8px'/>"
        f"<p style='color:#7b8bb0;font-size:12px'>Supervised intelligence tool — no live trades approved.</p>"
        f"</body></html>", "html", "utf-8"))
    msg.attach(alt)

    img = MIMEImage(png.read_bytes(), _subtype="png")
    img.add_header("Content-ID", "<shot>")
    img.add_header("Content-Disposition", "attachment", filename=png.name)
    msg.attach(img)

    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
    print("screenshot/email: sent to", recipient)
    return True


def latest_dashboard() -> Path | None:
    today = datetime.date.today().isoformat()
    todays = DASH_DIR / f"dashboard_{today}.html"
    if todays.exists():
        return todays
    files = sorted(DASH_DIR.glob("dashboard_*.html"))
    return files[-1] if files else None


def main() -> int:
    html = latest_dashboard()
    if html is None:
        print("screenshot: no dashboard_*.html found in", DASH_DIR)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("screenshot: playwright not installed — run:\n"
              "  pip install playwright && playwright install chromium")
        return 2

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SHOT_DIR / f"{html.stem}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[  # force software WebGL so the globe renders reliably headless
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--ignore-gpu-blocklist",
                "--enable-webgl",
            ],
        )
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
        # networkidle waits for globe.gl + textures (from unpkg) to finish loading
        page.goto(html.as_uri(), wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(RENDER_WAIT_MS)
        page.screenshot(path=str(out))
        browser.close()

    print("screenshot: saved", out)

    # Email it (non-fatal — a mail hiccup never fails the run).
    try:
        email_screenshot(out)
    except Exception as e:  # noqa: BLE001
        print("screenshot/email: failed —", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
