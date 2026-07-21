"""CMC pipeline entry point.

Usage:
    source .venv/bin/activate
    python -m cmc.run
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from cmc.config import load_config
from cmc.pipeline import alert_human as alert_human_stage
from cmc.pipeline import classify_signal as classify_signal_stage
from cmc.pipeline import deduplicate_events as deduplicate_events_stage
from cmc.pipeline import evidence_state as evidence_state_stage
from cmc.pipeline import fetch_market_data as fetch_market_data_stage
from cmc.pipeline import fetch_news_macro as fetch_news_macro_stage
from cmc.pipeline import journal_store as journal_store_stage
from cmc.pipeline import normalize as normalize_stage
from cmc.pipeline import generate_dashboard as generate_dashboard_stage
from cmc.pipeline import paper_trade as paper_trade_stage
from cmc.pipeline import risk_gate as risk_gate_stage
from cmc.pipeline import score_watchlist as score_watchlist_stage
from cmc.pipeline import summarize_brief as summarize_brief_stage
from cmc.pipeline import verify_signal as verify_signal_stage


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Keep third-party noise down
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def run_pipeline() -> dict:
    log = logging.getLogger("cmc.run")
    cfg = load_config()
    pipeline_cfg = cfg.get("pipeline", {})

    log.info("━━━ CMC pipeline starting ━━━")

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    log.info("[1/9] Fetching market data (yfinance)…")
    market_items = fetch_market_data_stage.fetch_market_data(cfg)
    log.info("      → %d price items", len(market_items))

    log.info("[2/9] Fetching news + macro (NewsAPI / FRED)…")
    news_macro_items = fetch_news_macro_stage.fetch_news_macro(cfg)
    log.info("      → %d news/macro items", len(news_macro_items))

    raw_items = [*market_items, *news_macro_items]

    # ── 2. Normalize + deduplicate + evidence label ───────────────────────────
    log.info("[3/9] Normalizing + deduplicating %d items…", len(raw_items))
    normalized = normalize_stage.normalize_items(raw_items, pipeline_cfg.get("normalize", {}))
    deduplicated = deduplicate_events_stage.deduplicate_events(
        normalized,
        pipeline_cfg.get("deduplicate", {}),
    )
    evidence_items = evidence_state_stage.label_evidence(deduplicated)
    log.info("      → %d unique items after dedup", len(evidence_items))

    # ── 3. Classify ───────────────────────────────────────────────────────────
    n_items = len(evidence_items)
    rpm = pipeline_cfg.get("classification", {}).get("requests_per_minute", 10)
    eta_min = n_items / rpm
    log.info(
        "[4/9] Classifying %d items via Gemini (RPM cap=%d, est. ~%.0f min)…",
        n_items, rpm, eta_min,
    )
    classified = classify_signal_stage.classify_signals(evidence_items, cfg)
    log.info("      → %d signals classified", len(classified))

    # ── 4. Verify ─────────────────────────────────────────────────────────────
    log.info("[5/9] Running 6 verification checks…")
    classification_cfg = pipeline_cfg.get("classification", {})
    verify_cfg = pipeline_cfg.get("verify", {})
    macro_items = [item for item in evidence_items if item.source_type == "macro"]
    passed, held = verify_signal_stage.verify_signals(
        classified,
        confidence_floor=classification_cfg.get("confidence_floor", 0.55),
        high_impact_threshold=verify_cfg.get("high_impact_threshold", 0.8),
        macro_items=macro_items,
    )
    log.info("      → %d passed, %d held for review", len(passed), len(held))

    # ── 5. Risk gate ──────────────────────────────────────────────────────────
    log.info("[6/9] Applying 5 risk gate rules…")
    approved, blocked = risk_gate_stage.apply_risk_gate(passed, cfg)
    log.info("      → %d approved, %d blocked", len(approved), len(blocked))

    # ── 6. Score ──────────────────────────────────────────────────────────────
    scored = score_watchlist_stage.score_watchlist(
        approved,
        pipeline_cfg.get("scoring", {}),
    )

    # ── 7. Brief + email ──────────────────────────────────────────────────────
    log.info("[7/9] Generating daily brief + email…")
    review_items = [*held, *blocked]
    brief = summarize_brief_stage.summarize_brief(scored, review_items, cfg)
    alert_result = alert_human_stage.alert_human(brief, cfg)

    # ── 8. Paper trade journal ────────────────────────────────────────────────
    log.info("[8/9] Logging paper trade candidates…")
    paper_entries = paper_trade_stage.log_paper_trades(approved, cfg)

    # ── 9. Generate dashboard ─────────────────────────────────────────────────
    log.info("[9/9] Generating Command Deck dashboard…")
    dashboard_path = generate_dashboard_stage.generate_dashboard(
        scored, review_items, macro_items, cfg
    )
    if dashboard_path:
        log.info("      → dashboard saved: %s", dashboard_path.name)

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = {
        "status": "completed",
        "run_completed_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "market_items": len(market_items),
            "news_macro_items": len(news_macro_items),
            "unique_after_dedup": len(evidence_items),
            "classified": len(classified),
            "passed_verify": len(passed),
            "held_for_review": len(held),
            "risk_approved": len(approved),
            "risk_blocked": len(blocked),
            "scored": len(scored),
            "paper_trades_logged": len(paper_entries),
        },
        "brief_chars": len(brief),
        "dashboard": str(dashboard_path) if dashboard_path else None,
        "alert": alert_result,
    }

    journal_store_stage.journal_event(
        {"event_type": "pipeline_run", "summary": summary}
    )

    log.info("━━━ CMC pipeline complete ━━━")
    _print_run_summary(summary)
    return summary


def _print_run_summary(s: dict) -> None:
    c = s["counts"]
    dashboard_name = s.get("dashboard")
    dashboard_line = f"data/dashboard/{dashboard_name.split('/')[-1]}" if dashboard_name else "skipped"
    print(f"""
┌─ CMC Run Summary ────────────────────────────────────┐
│  Fetched       {c['market_items']:>3} price  +  {c['news_macro_items']:>3} news/macro items
│  After dedup   {c['unique_after_dedup']:>3} unique items classified
│  Verify        {c['passed_verify']:>3} passed   /  {c['held_for_review']:>3} held for review
│  Risk gate     {c['risk_approved']:>3} approved /  {c['risk_blocked']:>3} blocked
│  Paper trades  {c['paper_trades_logged']:>3} logged
│  Brief         {s['brief_chars']:>4} chars  →  data/briefs/
│  Dashboard     →  {dashboard_line}
└──────────────────────────────────────────────────────┘""")


if __name__ == "__main__":
    _setup_logging()
    run_pipeline()
