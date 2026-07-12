"""Base input items flowing through Chief Market Cat."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib


VALID_SOURCE_TYPES = {
    "price",
    "news",
    "macro",
    "filing",
    "broker",
    "manual",
    "social",
}

VALID_TRUST_TIERS = {
    "official",
    "primary",
    "major_publisher",
    "market_data",
    "aggregator",
    "social",
}


@dataclass
class RawMarketItem:
    id: str
    asset: str
    market: str
    title: str
    body: str
    source_name: str
    source_type: str
    trust_tier: str = "aggregator"
    source_weight: float = 0.5
    region: str = "global"
    timestamp: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_metadata: dict = field(default_factory=dict)

    evidence_category: str = "aggregator"
    evidence_level: str = "headline_only"
    evidence_source: str = "unknown"
    enrichment_status: str = "skipped"
    enrichment_reason: str | None = None

    @staticmethod
    def generate_id(seed: str) -> str:
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


@dataclass
class NormalizedMarketItem(RawMarketItem):
    normalized_asset: str | None = None
    timeframe: str = "1d"
    filter_status: str = "kept"
    filter_reason: str | None = None
    duplicate_count: int = 0
    duplicate_source_names: list[str] = field(default_factory=list)
    duplicate_item_ids: list[str] = field(default_factory=list)

