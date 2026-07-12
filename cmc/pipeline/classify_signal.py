"""Classify normalized items into market signals using Gemini (gemini-1.5-flash).

Falls back to NEUTRAL/no_trade_unclear if Gemini is unavailable or the key is a placeholder.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from cmc.config import is_placeholder
from cmc.schemas.items import NormalizedMarketItem
from cmc.schemas.signals import SignalItem

log = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-1.5-flash"
NEEDS_REVIEW_THRESHOLD = 0.6

_SYSTEM_PROMPT = """\
You are a market signal classifier for Chief Market Cat (CMC).

Your job is to classify a single market signal based on:
- Recent price movement data
- Relevant news headlines
- Macro context (if available)

Return ONLY a valid JSON object with these exact fields:
{
  "signal_type": "<one of: trend_continuation, breakout, mean_reversion, volatility_expansion, volatility_compression, macro_regime_shift, earnings_event, policy_event, liquidity_stress, sentiment_dislocation, no_trade_unclear>",
  "direction": "<one of: BULLISH, BEARISH, NEUTRAL>",
  "confidence": <float between 0.0 and 1.0>,
  "rationale": "<1-2 sentence explanation citing specific evidence>",
  "invalidation": "<what would invalidate this signal — required if direction is BULLISH or BEARISH>"
}

Rules:
- Never assign BULLISH or BEARISH with confidence > 0.7 unless you have both price evidence AND fundamental/news evidence.
- Headlines-only evidence: cap confidence at 0.55.
- If macro headwinds conflict with the signal, lower confidence by 0.1 and flag it in rationale.
- If no clear signal, use signal_type: no_trade_unclear and direction: NEUTRAL.
- Do not include any text outside the JSON object.
"""


def classify_signals(items: list[NormalizedMarketItem], cfg: dict) -> list[SignalItem]:
    """
    Classify each normalized item using Gemini.

    If Gemini key is missing/placeholder, all items fall back to NEUTRAL classification.
    """
    secrets = cfg.get("secrets", {})
    gemini_key = secrets.get("gemini_key", "")

    if is_placeholder(gemini_key):
        log.info("classify_signal: Gemini key not configured — using NEUTRAL fallback for all signals")
        return [_neutral_signal(item, reason="gemini_key_not_configured") for item in items]

    # Import google.generativeai lazily so the module loads without the package installed
    try:
        import google.generativeai as genai  # type: ignore[import]
    except ImportError:
        log.warning(
            "classify_signal: google-generativeai not installed — "
            "run: pip install google-generativeai. Using NEUTRAL fallback."
        )
        return [_neutral_signal(item, reason="google_generativeai_not_installed") for item in items]

    genai.configure(api_key=gemini_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    # Gather macro context once (FRED items) to inject into each classification prompt
    macro_context = _build_macro_context(items)

    results: list[SignalItem] = []
    for item in items:
        try:
            classified = _classify_one(model, item, macro_context, cfg)
            results.append(classified)
        except Exception as exc:  # noqa: BLE001
            log.warning("classify_signal: Gemini failed for %s — %s", item.asset, exc)
            results.append(_neutral_signal(item, reason=f"gemini_error: {exc}"))

    log.info("classify_signal: classified %d signals", len(results))
    return results


def _classify_one(
    model: object,
    item: NormalizedMarketItem,
    macro_context: str,
    cfg: dict,
) -> SignalItem:
    """Call Gemini for a single item and return a classified SignalItem."""
    pipeline_cfg = cfg.get("pipeline", {})
    needs_review_threshold = (
        pipeline_cfg.get("classification", {}).get("needs_review_threshold", NEEDS_REVIEW_THRESHOLD)
    )

    # Build the user prompt from item metadata
    price_info = ""
    raw = item.raw_metadata or {}
    if raw.get("price") is not None:
        price_info = (
            f"Current Price: {raw['price']:.4f}\n"
            f"1-Day Change: {raw.get('change_1d_pct', 0):+.2f}%\n"
            f"5-Day Change: {raw.get('change_5d_pct', 0):+.2f}%\n"
            f"52W High proximity: {raw.get('pct_from_52w_high', 0):+.1f}%\n"
            f"52W Low proximity: {raw.get('pct_from_52w_low', 0):+.1f}%\n"
            f"Volume: {raw.get('volume', 'N/A')}\n"
        )

    user_prompt = f"""Classify this market signal.

Asset: {item.asset}
Market: {item.market}
Region: {item.region}
Source Type: {item.source_type}
Timestamp: {item.timestamp or 'unknown'}

--- PRICE DATA ---
{price_info if price_info else '(no price data)'}

--- HEADLINE / CONTENT ---
{item.title}
{item.body[:1500] if item.body else '(no body)'}

--- MACRO CONTEXT ---
{macro_context if macro_context else '(no macro data available)'}

Return only the JSON object.
"""

    response = model.generate_content(  # type: ignore[attr-defined]
        [{"role": "user", "parts": [_SYSTEM_PROMPT + "\n\n" + user_prompt]}]
    )
    raw_text = response.text.strip()

    # Strip markdown code fences if Gemini wraps the JSON
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
    raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE)

    parsed = json.loads(raw_text)

    signal_type = parsed.get("signal_type", "no_trade_unclear")
    direction = parsed.get("direction", "NEUTRAL").upper()
    confidence = float(parsed.get("confidence", 0.0))
    rationale = parsed.get("rationale", "")
    invalidation = parsed.get("invalidation") or None

    # Normalise direction to schema values
    if direction not in ("BULLISH", "BEARISH", "NEUTRAL"):
        direction = "NEUTRAL"

    needs_review = confidence < needs_review_threshold

    signal = SignalItem(
        **vars(item),
        signal_type=signal_type,
        direction=direction.lower(),          # schema stores lowercase
        confidence=confidence,
        rationale=rationale,
        invalidation=invalidation,
        relevance_score=min(confidence + 0.1, 1.0),
        evidence_score=_evidence_score(item),
        impact_score=_impact_score(confidence, direction),
        urgency_score=_urgency_score(item),
        liquidity_score=_liquidity_score(item),
    )

    if needs_review:
        signal.human_review_flag = True
        signal.human_review_reason = f"needs_review: confidence={confidence:.2f} below {needs_review_threshold}"

    log.info(
        "classify_signal: %s → %s %s (conf=%.2f, review=%s)",
        item.asset, direction, signal_type, confidence, needs_review,
    )
    return signal


def _build_macro_context(items: list[NormalizedMarketItem]) -> str:
    """Extract FRED macro items and format them as a context string."""
    macro_lines = []
    for item in items:
        if item.source_type == "macro" and item.raw_metadata:
            label = item.raw_metadata.get("label", item.asset)
            value = item.raw_metadata.get("latest_value")
            unit = item.raw_metadata.get("unit", "")
            date = item.raw_metadata.get("latest_date", "")
            if value is not None:
                macro_lines.append(f"- {label}: {value:.3f} {unit} (as of {date})")
    return "\n".join(macro_lines)


def _neutral_signal(item: NormalizedMarketItem, reason: str = "") -> SignalItem:
    return SignalItem(
        **vars(item),
        signal_type="no_trade_unclear",
        direction="neutral",
        confidence=0.0,
        rationale=f"No Gemini classification available. Reason: {reason}",
        human_review_flag=True,
        human_review_reason=reason,
    )


def _evidence_score(item: NormalizedMarketItem) -> float:
    if item.evidence_level == "price_feed":
        return 0.8
    if item.evidence_level == "article":
        return 0.6
    if item.evidence_level == "official_data":
        return 1.0
    return 0.3   # headline_only


def _impact_score(confidence: float, direction: str) -> float:
    if direction in ("BULLISH", "BEARISH", "bullish", "bearish"):
        return min(confidence * 1.2, 1.0)
    return 0.1


def _urgency_score(item: NormalizedMarketItem) -> float:
    """Higher urgency for same-day items."""
    if item.timestamp is None:
        return 0.3
    now = datetime.now(timezone.utc)
    ts = item.timestamp if item.timestamp.tzinfo else item.timestamp.replace(tzinfo=timezone.utc)
    hours_old = (now - ts).total_seconds() / 3600
    if hours_old <= 4:
        return 0.9
    if hours_old <= 12:
        return 0.7
    if hours_old <= 24:
        return 0.5
    return 0.2


def _liquidity_score(item: NormalizedMarketItem) -> float:
    """ETFs and major indices get higher liquidity scores."""
    liquid_assets = {"SPY", "QQQ", "GLD", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"}
    asset = (item.asset or "").upper()
    if asset in liquid_assets:
        return 0.9
    if asset.endswith(".AX"):
        return 0.7   # ASX large caps are liquid but less so than US mega-caps
    return 0.5
