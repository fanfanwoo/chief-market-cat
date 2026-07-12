"""Fetch market data from configured sources."""

from cmc.schemas.items import RawMarketItem


def fetch_market_data(cfg: dict) -> list[RawMarketItem]:
    from cmc.connectors.market_data_connector import fetch_market_data as fetch_from_connector

    return fetch_from_connector(cfg)
