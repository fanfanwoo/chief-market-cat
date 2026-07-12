"""Connector protocol definitions."""

from typing import Protocol

from cmc.schemas.items import RawMarketItem


class Connector(Protocol):
    def fetch(self) -> list[RawMarketItem]:
        """Fetch raw items from a source."""

