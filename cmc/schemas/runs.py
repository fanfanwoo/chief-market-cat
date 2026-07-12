"""Run-level schemas."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RunLog:
    run_id: str
    status: str = "started"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    items_fetched: int = 0
    items_normalized: int = 0
    signals_classified: int = 0
    signals_held: int = 0
    signals_scored: int = 0
    errors: list[dict] = field(default_factory=list)

