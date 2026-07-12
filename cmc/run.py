"""MVP 1 pipeline entry point."""

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
from cmc.pipeline import risk_gate as risk_gate_stage
from cmc.pipeline import score_watchlist as score_watchlist_stage
from cmc.pipeline import summarize_brief as summarize_brief_stage
from cmc.pipeline import verify_signal as verify_signal_stage


def run_pipeline() -> dict:
    cfg = load_config()
    pipeline_cfg = cfg.get("pipeline", {})

    market_items = fetch_market_data_stage.fetch_market_data(cfg)
    news_macro_items = fetch_news_macro_stage.fetch_news_macro(cfg)
    raw_items = [*market_items, *news_macro_items]

    normalized = normalize_stage.normalize_items(raw_items, pipeline_cfg.get("normalize", {}))
    deduplicated = deduplicate_events_stage.deduplicate_events(
        normalized,
        pipeline_cfg.get("deduplicate", {}),
    )
    evidence_items = evidence_state_stage.label_evidence(deduplicated)
    classified = classify_signal_stage.classify_signals(evidence_items, cfg)

    classification_cfg = pipeline_cfg.get("classification", {})
    verify_cfg = pipeline_cfg.get("verify", {})
    passed, held = verify_signal_stage.verify_signals(
        classified,
        confidence_floor=classification_cfg.get("confidence_floor", 0.55),
        high_impact_threshold=verify_cfg.get("high_impact_threshold", 0.8),
        macro_items=[item for item in evidence_items if item.source_type == "macro"],
    )

    approved, blocked = risk_gate_stage.apply_risk_gate(passed, cfg)
    scored = score_watchlist_stage.score_watchlist(
        approved,
        pipeline_cfg.get("scoring", {}),
    )
    review_items = [*held, *blocked]
    brief = summarize_brief_stage.summarize_brief(scored, review_items, cfg)
    alert_result = alert_human_stage.alert_human(brief, cfg)

    summary = {
        "status": "mvp1_completed",
        "run_completed_at": datetime.now(timezone.utc).isoformat(),
        "configured_sections": sorted(cfg.keys()),
        "counts": {
            "market_items": len(market_items),
            "news_macro_items": len(news_macro_items),
            "raw_items": len(raw_items),
            "normalized_items": len(normalized),
            "deduplicated_items": len(deduplicated),
            "classified_signals": len(classified),
            "passed_verify": len(passed),
            "held_for_review": len(held),
            "risk_approved": len(approved),
            "risk_blocked": len(blocked),
            "scored_signals": len(scored),
        },
        "brief_chars": len(brief),
        "alert": alert_result,
    }

    journal_result = journal_store_stage.journal_event(
        {
            "event_type": "mvp1_run_summary",
            "summary": summary,
        }
    )

    return {
        **summary,
        "journal": journal_result,
    }


if __name__ == "__main__":
    print(run_pipeline())
