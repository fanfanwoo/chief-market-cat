"""Create a daily market brief using Gemini and email it via Gmail SMTP.

If Gemini or Gmail keys are not configured, falls back gracefully:
  - No Gemini key → brief is built from a plain template (no AI prose)
  - No Gmail password → brief is saved to disk but not emailed
"""

from __future__ import annotations

import json
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from cmc.config import is_placeholder
from cmc.schemas.signals import ScoredSignal, SignalItem

log = logging.getLogger(__name__)

BRIEFS_DIR = Path(__file__).resolve().parents[2] / "data" / "briefs"

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465

_BRIEF_SYSTEM_PROMPT = """\
You are Chief Market Cat (CMC), a supervised market intelligence assistant.

Write a concise morning market brief from the structured signal data below.
The brief has three sections:

1. **Macro Pulse** (1 paragraph): summarise the current macro environment
   using the FRED data (yields, Fed Funds, VIX). Note direction and any
   notable divergences or stress signals.

2. **Top 3 Signals** (3 bullet points): for each top signal include:
   - Symbol and direction (BULLISH/BEARISH/NEUTRAL)
   - 1-sentence rationale citing specific evidence
   - Invalidation condition

3. **Risk Flags** (bullet list): surface any human_review signals, low-
   confidence calls, conflicting signals, or macro headwinds that the
   trader should be aware of before acting.

Rules:
- Separate evidence from interpretation.
- Never imply that live execution has been approved.
- Be direct. No fluff. Trader reading time < 90 seconds.
- Return plain markdown (no HTML).
"""


def summarize_brief(scored: list[ScoredSignal], held: list[SignalItem], cfg: dict) -> str:
    """
    Generate the daily market brief, save it to data/briefs/, and email it.

    Returns the markdown brief string.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    secrets = cfg.get("secrets", {})

    # ── Generate brief text ───────────────────────────────────────────────────
    gemini_key = secrets.get("gemini_key", "")
    if is_placeholder(gemini_key):
        log.info("summarize_brief: Gemini key not configured — using template brief")
        brief_md = _template_brief(scored, held, today)
    else:
        try:
            brief_md = _gemini_brief(gemini_key, scored, held, today, cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("summarize_brief: Gemini brief generation failed — %s. Using template.", exc)
            brief_md = _template_brief(scored, held, today)

    # ── Save to disk ──────────────────────────────────────────────────────────
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    brief_path = BRIEFS_DIR / f"brief_{today}.md"
    brief_path.write_text(brief_md, encoding="utf-8")
    log.info("summarize_brief: brief saved to %s", brief_path)

    # ── Email ─────────────────────────────────────────────────────────────────
    gmail_password = secrets.get("gmail_app_password", "")
    gmail_sender = secrets.get("gmail_sender", "fan2010.wu@gmail.com")
    gmail_recipient = secrets.get("gmail_recipient", "fan2010.wu@gmail.com")

    if is_placeholder(gmail_password):
        log.info("summarize_brief: Gmail App Password not configured — skipping email")
    else:
        try:
            _send_email(
                sender=gmail_sender,
                recipient=gmail_recipient,
                app_password=gmail_password,
                subject=f"CMC Daily Brief — {today}",
                body_md=brief_md,
            )
            log.info("summarize_brief: brief emailed to %s", gmail_recipient)
        except Exception as exc:  # noqa: BLE001
            log.warning("summarize_brief: email failed — %s", exc)

    return brief_md


# ── Gemini brief ───────────────────────────────────────────────────────────────

def _gemini_brief(
    api_key: str,
    scored: list[ScoredSignal],
    held: list[SignalItem],
    today: str,
    cfg: dict,
) -> str:
    import google.generativeai as genai  # type: ignore[import]

    genai.configure(api_key=api_key)
    pipeline_cfg = cfg.get("pipeline", {})
    class_cfg = pipeline_cfg.get("classification", {})
    # Prefer brief_model (higher quality); fall back to classifier model, then a safe default.
    model_name = class_cfg.get("brief_model") or class_cfg.get("model", "gemini-3.5-flash")
    model = genai.GenerativeModel(model_name)

    top_n = pipeline_cfg.get("summary", {}).get("top_signal_limit", 5)
    top_signals = scored[:top_n]

    signal_data = json.dumps(
        [_signal_to_dict(s) for s in top_signals],
        indent=2,
        default=str,
    )
    held_data = json.dumps(
        [_signal_to_dict(s) for s in held[:5]],
        indent=2,
        default=str,
    )

    user_prompt = f"""Date: {today}

--- TOP SIGNALS (ranked by watchlist score) ---
{signal_data}

--- HELD FOR REVIEW ---
{held_data}

Write the morning market brief following the system instructions.
"""

    response = model.generate_content(
        [{"role": "user", "parts": [_BRIEF_SYSTEM_PROMPT + "\n\n" + user_prompt]}]
    )
    text = response.text.strip()

    # Strip code fences if present
    text = re.sub(r"^```(?:markdown)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)

    header = f"# Chief Market Cat Daily Brief — {today}\n\n"
    return header + text


# ── Template brief (no Gemini) ─────────────────────────────────────────────────

def _template_brief(scored: list[ScoredSignal], held: list[SignalItem], today: str) -> str:
    lines = [
        f"# Chief Market Cat Daily Brief — {today}",
        "",
        "## Macro Pulse",
        "",
        "_Gemini key not configured — macro summary unavailable._",
        "",
        "## Top Signals",
        "",
    ]

    if not scored:
        lines.append("- No scored signals available for this run.")
    else:
        for signal in scored[:3]:
            direction = signal.direction.upper()
            conf = f"{signal.confidence:.0%}"
            lines.append(
                f"- **{signal.asset}** [{direction}] conf={conf} — "
                f"{signal.rationale or 'No rationale.'} "
                f"| Invalidation: {signal.invalidation or 'not set'}"
            )

    lines += [
        "",
        "## Risk Flags",
        "",
    ]

    if not held:
        lines.append("- No signals held for human review.")
    else:
        for signal in held:
            reason = signal.human_review_reason or "review required"
            lines.append(f"- **{signal.asset}**: {reason}")

    lines += [
        "",
        "---",
        "_CMC is a supervised intelligence tool. No live trades have been approved._",
    ]
    return "\n".join(lines)


# ── Email helper ───────────────────────────────────────────────────────────────

def _send_email(
    sender: str,
    recipient: str,
    app_password: str,
    subject: str,
    body_md: str,
) -> None:
    """Send the brief via Gmail SMTP using an App Password."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    # Plain text part (markdown is readable as plain text)
    part_plain = MIMEText(body_md, "plain", "utf-8")
    msg.attach(part_plain)

    # Minimal HTML wrapper for email clients that prefer it
    html_body = (
        "<html><body><pre style='font-family:monospace;white-space:pre-wrap;'>"
        + body_md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre></body></html>"
    )
    part_html = MIMEText(html_body, "html", "utf-8")
    msg.attach(part_html)

    # Seed the CA store from certifi — python.org builds ship without system
    # root certificates, which otherwise fails SMTP_SSL cert verification.
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, context=context) as server:
        server.login(sender, app_password)
        server.sendmail(sender, [recipient], msg.as_string())


# ── Utility ────────────────────────────────────────────────────────────────────

def _signal_to_dict(signal: SignalItem) -> dict:
    return {
        "asset": signal.asset,
        "direction": signal.direction,
        "signal_type": signal.signal_type,
        "confidence": signal.confidence,
        "rationale": signal.rationale,
        "invalidation": signal.invalidation,
        "human_review_flag": signal.human_review_flag,
        "human_review_reason": signal.human_review_reason,
        "risk_flags": signal.risk_flags,
        "raw_metadata": signal.raw_metadata,
    }
