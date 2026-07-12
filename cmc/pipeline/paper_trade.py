"""Paper trading journal — logs approved signals as paper trade entries.

For each approved signal (passed risk gate), writes a trade entry with:
  - symbol, direction, entry_price (current price from market data)
  - position_size (calculated from risk.yaml sizing rules)
  - stop_loss (2% below entry for BULLISH, 2% above for BEARISH)
  - take_profit (4% from entry, 2:1 R/R ratio)
  - timestamp, rationale, signal metadata

Entries are appended to data/journal/YYYY-MM-DD.jsonl (one file per day).
A summary is printed to stdout at the end of each run.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from cmc.schemas.signals import SignalItem

log = logging.getLogger(__name__)

JOURNAL_DIR = Path(__file__).resolve().parents[2] / "data" / "journal"


def log_paper_trades(
    approved_signals: list[SignalItem],
    cfg: dict,
) -> list[dict]:
    """
    Convert approved signals to paper trade entries and persist them.

    Args:
        approved_signals: Signals that have passed both verify and risk gate.
        cfg:              Full config dict (reads cfg['risk'] for sizing params).

    Returns:
        List of trade entry dicts that were written.
    """
    risk_cfg = cfg.get("risk", {})
    sizing_cfg = risk_cfg.get("position_sizing", {})

    stop_loss_pct: float = sizing_cfg.get("stop_loss_pct", 2.0)
    take_profit_pct: float = sizing_cfg.get("take_profit_pct", 4.0)
    notional_account: float = sizing_cfg.get("notional_account_aud", 10_000.0)
    risk_per_trade_pct: float = sizing_cfg.get("default_risk_per_trade_pct", 0.5)

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    entries: list[dict] = []

    for signal in approved_signals:
        entry_price = _get_price(signal)
        if entry_price is None:
            log.warning(
                "paper_trade: no price data for %s — skipping journal entry",
                signal.asset,
            )
            continue

        direction = (signal.direction or "neutral").lower()

        # ── Position sizing ───────────────────────────────────────────────────
        # Risk amount = notional_account * risk_per_trade_pct / 100
        # Stop distance = entry_price * stop_loss_pct / 100
        # Position size (units) = risk_amount / stop_distance
        risk_amount_aud = notional_account * (risk_per_trade_pct / 100.0)
        stop_distance = entry_price * (stop_loss_pct / 100.0)
        position_units = risk_amount_aud / stop_distance if stop_distance > 0 else 0.0
        position_value_aud = position_units * entry_price

        # ── Stop & target levels ──────────────────────────────────────────────
        if direction == "bullish":
            stop_loss_price = entry_price * (1 - stop_loss_pct / 100.0)
            take_profit_price = entry_price * (1 + take_profit_pct / 100.0)
        elif direction == "bearish":
            stop_loss_price = entry_price * (1 + stop_loss_pct / 100.0)
            take_profit_price = entry_price * (1 - take_profit_pct / 100.0)
        else:
            # NEUTRAL signals don't get a directional trade
            log.info(
                "paper_trade: %s direction=NEUTRAL — logged as monitor, no sizing",
                signal.asset,
            )
            stop_loss_price = None
            take_profit_price = None
            position_units = 0.0
            position_value_aud = 0.0

        entry: dict = {
            "run_date": today_str,
            "timestamp_utc": now.isoformat(),
            "symbol": signal.asset,
            "market": signal.market,
            "direction": direction,
            "signal_type": signal.signal_type,
            "entry_price": round(entry_price, 4),
            "stop_loss_price": round(stop_loss_price, 4) if stop_loss_price else None,
            "take_profit_price": round(take_profit_price, 4) if take_profit_price else None,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "position_units": round(position_units, 4),
            "position_value_aud": round(position_value_aud, 2),
            "risk_amount_aud": round(risk_amount_aud, 2),
            "notional_account_aud": notional_account,
            "confidence": signal.confidence,
            "rationale": signal.rationale or "",
            "invalidation": signal.invalidation or "",
            "risk_flags": signal.risk_flags,
            "status": "open",          # lifecycle: open → closed
            "outcome_pct": None,       # filled in when trade is closed
            "closed_at": None,
            "close_price": None,
        }
        entries.append(entry)

    # ── Persist to JSONL ──────────────────────────────────────────────────────
    if entries:
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        journal_path = JOURNAL_DIR / f"{today_str}.jsonl"

        with journal_path.open("a", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry, default=str) + "\n")

        log.info(
            "paper_trade: wrote %d entries to %s",
            len(entries), journal_path,
        )

    # ── Print summary ─────────────────────────────────────────────────────────
    _print_summary(entries, today_str)

    return entries


def _get_price(signal: SignalItem) -> float | None:
    """Extract current price from raw_metadata, falling back to None."""
    raw = signal.raw_metadata or {}
    price = raw.get("price")
    if price is not None:
        try:
            return float(price)
        except (TypeError, ValueError):
            pass
    return None


def _print_summary(entries: list[dict], today_str: str) -> None:
    """Print a human-readable summary of today's paper trade candidates."""
    print(f"\n{'='*60}")
    print(f"  CMC Paper Trade Candidates — {today_str}")
    print(f"{'='*60}")

    if not entries:
        print("  No approved signals to log today.")
        print(f"{'='*60}\n")
        return

    for i, entry in enumerate(entries, 1):
        direction_icon = {
            "bullish": "▲",
            "bearish": "▼",
            "neutral": "◆",
        }.get(entry["direction"], "?")

        print(
            f"\n  {i}. {entry['symbol']} {direction_icon} {entry['direction'].upper()}"
            f" | conf={entry['confidence']:.0%}"
            f" | signal={entry['signal_type']}"
        )
        print(f"     Entry:  {entry['entry_price']}")
        if entry["stop_loss_price"]:
            print(
                f"     Stop:   {entry['stop_loss_price']}"
                f"  ({entry['stop_loss_pct']}% away)"
            )
        if entry["take_profit_price"]:
            print(
                f"     Target: {entry['take_profit_price']}"
                f"  ({entry['take_profit_pct']}% away)"
            )
        if entry["position_units"]:
            print(
                f"     Size:   {entry['position_units']:.2f} units"
                f"  ≈ AUD {entry['position_value_aud']:.2f}"
                f"  (risk: AUD {entry['risk_amount_aud']:.2f})"
            )
        if entry["rationale"]:
            # Truncate long rationale for console
            rationale_short = entry["rationale"][:120]
            if len(entry["rationale"]) > 120:
                rationale_short += "…"
            print(f"     Thesis: {rationale_short}")
        if entry["invalidation"]:
            print(f"     Invalidation: {entry['invalidation']}")

    total_risk = sum(e["risk_amount_aud"] for e in entries)
    total_exposure = sum(e["position_value_aud"] for e in entries)
    print(f"\n  Total: {len(entries)} candidates")
    print(f"  Total risk exposure: AUD {total_risk:.2f}")
    print(f"  Total position value: AUD {total_exposure:.2f}")
    print(f"\n  ⚠️  Paper trading only — no live orders placed.")
    print(f"{'='*60}\n")
