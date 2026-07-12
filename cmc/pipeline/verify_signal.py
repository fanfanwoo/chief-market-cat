"""Deterministic verify gate for signal pass/hold routing.

6 rule-based checks:
  1. low_confidence          — signal confidence below floor
  2. headline_only_high_impact — high-impact signal backed only by headlines
  3. missing_invalidation    — actionable signal has no invalidation condition
  4. price_vs_ai_direction   — price move contradicts AI direction classification
  5. stale_news              — all supporting news headlines are older than 24 hours
  6. macro_headwind          — signal direction conflicts with current macro trend
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from cmc.schemas.signals import SignalItem

log = logging.getLogger(__name__)

HOLD_REASONS = {
    "low_confidence",
    "headline_only_high_impact",
    "missing_invalidation",
    "price_vs_ai_direction",
    "stale_news",
    "macro_headwind",
}

# Macro series IDs that indicate rising-rate / risk-off environment
RATE_SENSITIVE_SYMBOLS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "QQQ",  # tech-heavy index
    "CBA.AX", "WBC.AX", "ANZ.AX", "NAB.AX",  # rate-sensitive banks
}


def verify_signals(
    signals: list[SignalItem],
    confidence_floor: float,
    high_impact_threshold: float,
    macro_items: list | None = None,
) -> tuple[list[SignalItem], list[SignalItem]]:
    """
    Apply all 6 verification checks to each signal.

    Returns:
        (passed_signals, held_signals)

    macro_items: optional list of RawMarketItem/NormalizedMarketItem from FRED —
                 used by the macro_headwind check.
    """
    macro_context = _extract_macro_context(macro_items or [])

    passed: list[SignalItem] = []
    held: list[SignalItem] = []

    for signal in signals:
        reasons = _reasons_for(signal, confidence_floor, high_impact_threshold, macro_context)
        if reasons:
            signal.human_review_flag = True
            signal.human_review_reason = ", ".join(reasons)
        if any(reason in HOLD_REASONS for reason in reasons):
            held.append(signal)
        else:
            passed.append(signal)

    log.info(
        "verify_signals: %d passed, %d held for review",
        len(passed), len(held),
    )
    return passed, held


def _reasons_for(
    signal: SignalItem,
    confidence_floor: float,
    high_impact_threshold: float,
    macro_context: dict,
) -> list[str]:
    reasons: list[str] = []

    # ── Check 1: low_confidence ───────────────────────────────────────────────
    if signal.confidence < confidence_floor:
        reasons.append("low_confidence")

    # ── Check 2: headline_only_high_impact ────────────────────────────────────
    if signal.evidence_level == "headline_only" and signal.impact_score >= high_impact_threshold:
        reasons.append("headline_only_high_impact")

    # ── Check 3: missing_invalidation ─────────────────────────────────────────
    if signal.signal_type != "no_trade_unclear" and not signal.invalidation:
        reasons.append("missing_invalidation")

    # ── Check 4: price_vs_ai_direction ────────────────────────────────────────
    # Flag if the observed price move contradicts the AI's classification.
    raw = signal.raw_metadata or {}
    change_1d = raw.get("change_1d_pct")
    direction = (signal.direction or "").lower()

    if change_1d is not None:
        price_moved_up = change_1d > 0.5     # meaningful up move
        price_moved_down = change_1d < -0.5  # meaningful down move

        if direction == "bearish" and price_moved_up:
            reasons.append("price_vs_ai_direction")
            log.debug(
                "verify: %s flagged price_vs_ai_direction — "
                "AI=BEARISH but 1d change=+%.2f%%",
                signal.asset, change_1d,
            )
        elif direction == "bullish" and price_moved_down:
            reasons.append("price_vs_ai_direction")
            log.debug(
                "verify: %s flagged price_vs_ai_direction — "
                "AI=BULLISH but 1d change=%.2f%%",
                signal.asset, change_1d,
            )

    # ── Check 5: stale_news ───────────────────────────────────────────────────
    # Flag if the signal's timestamp is older than 24 hours (i.e., no fresh news).
    if signal.source_type in ("news", "manual"):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        ts = signal.timestamp
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                reasons.append("stale_news")
                log.debug(
                    "verify: %s flagged stale_news — timestamp %s is > 24h old",
                    signal.asset, signal.timestamp,
                )

    # ── Check 6: macro_headwind ───────────────────────────────────────────────
    # Flag if signal direction conflicts with current macro regime.
    # Heuristic: rising 10Y yields (>4.5%) or rising VIX (>20) are headwinds
    # for BULLISH calls on rate-sensitive / growth stocks.
    if direction == "bullish" and signal.asset in RATE_SENSITIVE_SYMBOLS:
        us10y = macro_context.get("DGS10")
        vix = macro_context.get("VIXCLS")

        headwind_triggered = False
        headwind_detail = []

        if us10y is not None and us10y > 4.5:
            headwind_triggered = True
            headwind_detail.append(f"US10Y={us10y:.2f}%")

        if vix is not None and vix > 20:
            headwind_triggered = True
            headwind_detail.append(f"VIX={vix:.1f}")

        if headwind_triggered:
            reasons.append("macro_headwind")
            log.debug(
                "verify: %s flagged macro_headwind — BULLISH vs %s",
                signal.asset, ", ".join(headwind_detail),
            )

    return reasons


def _extract_macro_context(macro_items: list) -> dict:
    """
    Build a dict of {series_id: latest_value} from FRED macro items.
    Works with both RawMarketItem and NormalizedMarketItem.
    """
    context: dict[str, float] = {}
    for item in macro_items:
        raw = getattr(item, "raw_metadata", None) or {}
        series_id = raw.get("series_id") or getattr(item, "asset", None)
        value = raw.get("latest_value")
        if series_id and value is not None:
            try:
                context[series_id] = float(value)
            except (TypeError, ValueError):
                pass
    return context
