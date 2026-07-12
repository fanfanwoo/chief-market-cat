"""Normalize raw market items into shared pipeline records."""

from cmc.schemas.items import NormalizedMarketItem, RawMarketItem


def normalize_items(items: list[RawMarketItem], cfg: dict) -> list[NormalizedMarketItem]:
    timeframe = cfg.get("default_timeframe", "1d")
    return [
        NormalizedMarketItem(
            **vars(item),
            normalized_asset=item.asset.upper() if item.asset else None,
            timeframe=timeframe,
        )
        for item in items
    ]

