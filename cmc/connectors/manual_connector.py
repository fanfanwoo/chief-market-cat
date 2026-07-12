"""Manual connector for Phase 0 fixtures and hand-entered snapshots."""

from cmc.schemas.items import RawMarketItem


def fetch_manual_items(items: list[dict]) -> list[RawMarketItem]:
    return [RawMarketItem(**item) for item in items]

