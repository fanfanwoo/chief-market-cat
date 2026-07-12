"""Risk gate — 5 hard filter rules before a signal can become a trade candidate.

Rules:
  1. missing_invalidation    — signal has no invalidation condition (original)
  2. blocked_symbols         — symbol is on the configured blocked list
  3. weak_evidence           — fewer than 2 corroborating sources
  4. low_conviction_position_add — same symbol already open, requires confidence > 0.8
  5. sector_cap              — max 3 signals per sector, 10 signals total per run
"""

from __future__ import annotations

import logging

from cmc.schemas.signals import SignalItem

log = logging.getLogger(__name__)


def apply_risk_gate(
    signals: list[SignalItem],
    cfg: dict,
    open_positions: dict[str, str] | None = None,
) -> tuple[list[SignalItem], list[SignalItem]]:
    """
    Apply all 5 risk gate rules.

    Args:
        signals:         Verified signals to evaluate.
        cfg:             Full config dict (uses cfg['risk'] and cfg['sources']).
        open_positions:  Dict of {symbol: direction} for currently open paper positions.
                         Used for rule 4 (low_conviction_position_add).

    Returns:
        (approved_signals, blocked_signals)
    """
    risk_cfg = cfg.get("risk", {})
    sources_cfg = cfg.get("sources", {})

    gate_cfg = risk_cfg.get("risk_gate", {})
    require_invalidation = gate_cfg.get("require_invalidation", True)

    # Rule 2: blocked symbols list
    blocked_symbols_list: list[str] = risk_cfg.get("blocked_symbols", [])
    blocked_symbols_set = {s.upper() for s in blocked_symbols_list}

    # Rule 5: sector caps
    sector_caps = risk_cfg.get("sector_caps", {})
    max_per_sector: int = sector_caps.get("max_per_sector", 3)
    max_total: int = sector_caps.get("max_total", 10)
    sector_map: dict[str, str] = sources_cfg.get("sector_map", {})

    open_positions = open_positions or {}

    approved: list[SignalItem] = []
    blocked: list[SignalItem] = []

    # Sector counters — built as signals are approved, not pre-filtered
    sector_counts: dict[str, int] = {}
    total_approved = 0

    for signal in signals:
        reasons: list[str] = []
        asset_upper = (signal.asset or "").upper()

        # ── Rule 1: missing_invalidation ─────────────────────────────────────
        if (
            require_invalidation
            and signal.signal_type != "no_trade_unclear"
            and not signal.invalidation
        ):
            reasons.append("risk_missing_invalidation")

        # ── Rule 2: blocked_symbols ───────────────────────────────────────────
        if asset_upper in blocked_symbols_set:
            reasons.append(f"risk_blocked_symbol:{signal.asset}")
            log.info("risk_gate: %s is on the blocked symbols list", signal.asset)

        # ── Rule 3: weak_evidence — require at least 2 corroborating sources ──
        # We use duplicate_count + 1 (the signal itself) as a proxy for
        # corroborating source count. A signal that was deduplicated from
        # multiple sources has duplicate_count > 0.
        source_count = 1 + (signal.duplicate_count or 0)
        if source_count < 2 and signal.signal_type != "no_trade_unclear":
            reasons.append("risk_weak_evidence")
            log.debug(
                "risk_gate: %s has only %d source(s) — requires ≥2 for actionable signal",
                signal.asset, source_count,
            )

        # ── Rule 4: low_conviction_position_add ───────────────────────────────
        # If the same symbol is already in the open paper positions,
        # we require confidence > 0.8 before adding another signal.
        if signal.asset in open_positions or asset_upper in open_positions:
            existing_direction = open_positions.get(signal.asset) or open_positions.get(asset_upper)
            if signal.confidence <= 0.8:
                reasons.append(
                    f"risk_low_conviction_position_add:"
                    f"existing={existing_direction},conf={signal.confidence:.2f}"
                )
                log.info(
                    "risk_gate: %s already open (%s), new signal confidence=%.2f < 0.80",
                    signal.asset, existing_direction, signal.confidence,
                )

        # ── Rule 5: sector_cap ────────────────────────────────────────────────
        # Apply AFTER other rules pass — cap is per-run, not total blocked count.
        if not reasons:
            # Only check cap for signals that would otherwise be approved
            sector = sector_map.get(signal.asset, "unknown")
            current_sector_count = sector_counts.get(sector, 0)

            if total_approved >= max_total:
                reasons.append(f"risk_sector_cap:total_limit_reached:{max_total}")
                log.info(
                    "risk_gate: total signal cap of %d reached — blocking %s",
                    max_total, signal.asset,
                )
            elif current_sector_count >= max_per_sector:
                reasons.append(
                    f"risk_sector_cap:sector={sector}:limit={max_per_sector}"
                )
                log.info(
                    "risk_gate: sector '%s' cap of %d reached — blocking %s",
                    sector, max_per_sector, signal.asset,
                )

        # ── Routing ───────────────────────────────────────────────────────────
        if reasons:
            signal.risk_flags.extend(reasons)
            blocked.append(signal)
        else:
            # Count this signal toward sector/total caps
            sector = sector_map.get(signal.asset, "unknown")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            total_approved += 1
            approved.append(signal)

    log.info(
        "risk_gate: %d approved, %d blocked",
        len(approved), len(blocked),
    )
    return approved, blocked
