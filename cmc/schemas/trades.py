"""Trade decision memo schemas."""

from dataclasses import dataclass, field


@dataclass
class TradeMemo:
    asset: str
    direction: str
    timeframe: str
    thesis: str
    entry_zone: str | None = None
    invalidation: str | None = None
    stop: str | None = None
    target: str | None = None
    position_size_logic: str | None = None
    max_loss: str | None = None
    execution_notes: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    decision: str = "monitor"

