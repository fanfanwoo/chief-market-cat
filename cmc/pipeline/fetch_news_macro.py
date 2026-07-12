"""Fetch news, filing and macro items from configured sources."""

from cmc.schemas.items import RawMarketItem


def fetch_news_macro(cfg: dict) -> list[RawMarketItem]:
    from cmc.connectors.news_connector import fetch_news

    return fetch_news(cfg)
