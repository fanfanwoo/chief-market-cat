"""Signal schemas produced after classification."""

from dataclasses import dataclass, field

from cmc.schemas.items import NormalizedMarketItem


VALID_SIGNAL_TYPES = {
    "trend_continuation",
    "breakout",
    "mean_reversion",
    "volatility_expansion",
    "volatility_compression",
    "macro_regime_shift",
    "earnings_event",
    "policy_event",
    "liquidity_stress",
    "sentiment_dislocation",
    "no_trade_unclear",
}


@dataclass
class SignalItem(NormalizedMarketItem):
    signal_type: str = "no_trade_unclear"
    direction: str = "unclear"
    relevance_score: float = 0.0
    evidence_score: float = 0.0
    impact_score: float = 0.0
    urgency_score: float = 0.0
    liquidity_score: float = 0.0
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""
    invalidation: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    human_review_flag: bool = False
    human_review_reason: str | None = None


@dataclass
class ScoredSignal(SignalItem):
    watchlist_score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)
    rank: int | None = None

