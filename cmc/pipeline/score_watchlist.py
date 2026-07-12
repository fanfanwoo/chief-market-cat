"""Score verified signals for watchlist ranking."""

from cmc.schemas.signals import ScoredSignal, SignalItem


def score_watchlist(signals: list[SignalItem], cfg: dict) -> list[ScoredSignal]:
    weights = cfg.get("weights", {})
    scored = []
    for signal in signals:
        score = (
            weights.get("relevance", 0.25) * signal.relevance_score
            + weights.get("evidence", 0.25) * signal.evidence_score
            + weights.get("impact", 0.2) * signal.impact_score
            + weights.get("urgency", 0.15) * signal.urgency_score
            + weights.get("liquidity", 0.1) * signal.liquidity_score
            + weights.get("confidence", 0.05) * signal.confidence
        )
        scored.append(ScoredSignal(**vars(signal), watchlist_score=score))

    scored.sort(key=lambda item: item.watchlist_score, reverse=True)
    for index, signal in enumerate(scored, start=1):
        signal.rank = index
    return scored

