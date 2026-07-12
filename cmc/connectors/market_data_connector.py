"""Market data connector — fetches OHLCV data via yfinance for watchlist symbols."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from cmc.schemas.items import RawMarketItem

log = logging.getLogger(__name__)


def fetch_market_data(cfg: dict) -> list[RawMarketItem]:
    """
    Fetch last 2 days of OHLCV for every symbol in the watchlist.

    For each symbol computes:
      - current price (last close)
      - 1-day % change
      - 5-day % change
      - distance from 52-week high/low (expressed as %)
      - volume

    Returns a list of RawMarketItem objects, one per successfully fetched symbol.
    Failed symbols are skipped with a warning log.
    """
    import yfinance as yf

    sources_cfg = cfg.get("sources", {})
    watchlist: dict[str, list[str]] = sources_cfg.get("watchlist", {})
    all_symbols: list[str] = []
    for market_symbols in watchlist.values():
        all_symbols.extend(market_symbols)

    if not all_symbols:
        log.warning("market_data_connector: watchlist is empty — check config/sources.yaml")
        return []

    items: list[RawMarketItem] = []
    fetched_at = datetime.now(timezone.utc)

    for symbol in all_symbols:
        try:
            ticker = yf.Ticker(symbol)

            # Fetch 2 trading days for the daily % change
            hist_2d = ticker.history(period="2d")
            if hist_2d.empty or len(hist_2d) < 1:
                log.warning("market_data_connector: no data returned for %s — skipping", symbol)
                continue

            current_price = float(hist_2d["Close"].iloc[-1])
            volume = int(hist_2d["Volume"].iloc[-1])

            # 1-day % change
            if len(hist_2d) >= 2:
                prev_close = float(hist_2d["Close"].iloc[-2])
                change_1d_pct = ((current_price - prev_close) / prev_close) * 100.0
            else:
                change_1d_pct = 0.0

            # 5-day % change — fetch 7 calendar days to guarantee 5 trading days
            hist_5d = ticker.history(period="7d")
            if len(hist_5d) >= 5:
                close_5d_ago = float(hist_5d["Close"].iloc[-5])
                change_5d_pct = ((current_price - close_5d_ago) / close_5d_ago) * 100.0
            else:
                change_5d_pct = change_1d_pct  # fallback

            # 52-week high/low proximity
            hist_52w = ticker.history(period="1y")
            if not hist_52w.empty:
                high_52w = float(hist_52w["High"].max())
                low_52w = float(hist_52w["Low"].min())
                pct_from_52w_high = ((current_price - high_52w) / high_52w) * 100.0
                pct_from_52w_low = ((current_price - low_52w) / low_52w) * 100.0
            else:
                high_52w = current_price
                low_52w = current_price
                pct_from_52w_high = 0.0
                pct_from_52w_low = 0.0

            # Determine market region from symbol suffix
            region = "ASX" if symbol.endswith(".AX") else "US"

            # Build a human-readable title and body for the pipeline to consume
            direction_str = "▲" if change_1d_pct >= 0 else "▼"
            title = (
                f"{symbol} {direction_str} {change_1d_pct:+.2f}% | "
                f"Price: {current_price:.2f}"
            )
            body = (
                f"Symbol: {symbol}\n"
                f"Current Price: {current_price:.4f}\n"
                f"1D Change: {change_1d_pct:+.2f}%\n"
                f"5D Change: {change_5d_pct:+.2f}%\n"
                f"Volume: {volume:,}\n"
                f"52W High: {high_52w:.4f} ({pct_from_52w_high:+.1f}% from high)\n"
                f"52W Low: {low_52w:.4f} ({pct_from_52w_low:+.1f}% from low)\n"
                f"Region: {region}"
            )

            item_id = RawMarketItem.generate_id(f"yfinance:{symbol}:{fetched_at.date()}")

            item = RawMarketItem(
                id=item_id,
                asset=symbol,
                market=region,
                title=title,
                body=body,
                source_name="yfinance",
                source_type="price",
                trust_tier="market_data",
                source_weight=0.9,
                region=region,
                timestamp=fetched_at,
                fetched_at=fetched_at,
                evidence_category="market_data",
                evidence_level="price_feed",
                evidence_source="yfinance",
                enrichment_status="complete",
                raw_metadata={
                    "symbol": symbol,
                    "price": current_price,
                    "change_1d_pct": change_1d_pct,
                    "change_5d_pct": change_5d_pct,
                    "volume": volume,
                    "high_52w": high_52w,
                    "low_52w": low_52w,
                    "pct_from_52w_high": pct_from_52w_high,
                    "pct_from_52w_low": pct_from_52w_low,
                    "region": region,
                },
            )
            items.append(item)
            log.info(
                "market_data_connector: %s fetched — price=%.2f, 1d=%+.2f%%",
                symbol, current_price, change_1d_pct,
            )

        except Exception as exc:  # noqa: BLE001
            log.warning("market_data_connector: failed to fetch %s — %s", symbol, exc)
            continue

    log.info("market_data_connector: fetched %d/%d symbols", len(items), len(all_symbols))
    return items
