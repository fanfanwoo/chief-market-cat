"""News & macro connector — fetches from NewsAPI and FRED."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from cmc.config import is_placeholder
from cmc.schemas.items import RawMarketItem

log = logging.getLogger(__name__)

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/top-headlines"
FRED_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"

# FRED macro indicators to monitor
FRED_SERIES = [
    {"id": "DGS10",    "label": "US 10Y Treasury Yield",   "unit": "%"},
    {"id": "FEDFUNDS", "label": "Fed Funds Rate",           "unit": "%"},
    {"id": "VIXCLS",   "label": "VIX (Volatility Index)",  "unit": "points"},
]


def fetch_news(cfg: dict) -> list[RawMarketItem]:
    """
    Fetch top business/finance headlines from NewsAPI and current macro
    indicator readings from FRED.

    Returns a combined list of RawMarketItem objects.
    API keys are loaded from cfg['secrets']. If a key is missing or still
    a placeholder, that source is skipped gracefully.
    """
    secrets = cfg.get("secrets", {})
    items: list[RawMarketItem] = []

    items.extend(_fetch_newsapi(secrets))
    items.extend(_fetch_fred(secrets))

    log.info("news_connector: returned %d items total", len(items))
    return items


# ── NewsAPI ────────────────────────────────────────────────────────────────────

def _fetch_newsapi(secrets: dict) -> list[RawMarketItem]:
    import requests

    api_key = secrets.get("newsapi_key", "")
    if is_placeholder(api_key):
        log.info("news_connector: NewsAPI key not configured — skipping NewsAPI fetch")
        return []

    fetched_at = datetime.now(timezone.utc)
    since = fetched_at - timedelta(hours=24)

    params = {
        "apiKey": api_key,
        "category": "business",
        "language": "en",
        "pageSize": 20,
    }

    try:
        response = requests.get(NEWSAPI_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        log.warning("news_connector: NewsAPI request failed — %s", exc)
        return []

    articles = data.get("articles", [])
    items: list[RawMarketItem] = []

    for article in articles:
        published_raw = article.get("publishedAt") or ""
        try:
            pub_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            pub_dt = fetched_at

        # Skip articles older than 24 hours
        if pub_dt < since:
            continue

        title = (article.get("title") or "").strip()
        description = (article.get("description") or "").strip()
        content = (article.get("content") or description).strip()
        url = article.get("url") or ""
        source_name_raw = (article.get("source") or {}).get("name") or "newsapi"

        if not title:
            continue

        item_id = RawMarketItem.generate_id(f"newsapi:{url}:{published_raw}")

        item = RawMarketItem(
            id=item_id,
            asset="MARKET",          # headline-level; no specific asset attached
            market="global",
            title=title,
            body=f"{description}\n\n{content}\n\nURL: {url}".strip(),
            source_name=source_name_raw,
            source_type="news",
            trust_tier="major_publisher",
            source_weight=0.75,
            region="global",
            timestamp=pub_dt,
            fetched_at=fetched_at,
            evidence_category="news",
            evidence_level="headline_only" if not content else "article",
            evidence_source="newsapi",
            enrichment_status="complete",
            raw_metadata={
                "url": url,
                "published_at": published_raw,
                "source": source_name_raw,
            },
        )
        items.append(item)

    log.info("news_connector: NewsAPI returned %d articles", len(items))
    return items


# ── FRED ───────────────────────────────────────────────────────────────────────

def _fetch_fred(secrets: dict) -> list[RawMarketItem]:
    import requests

    api_key = secrets.get("fred_key", "")
    if is_placeholder(api_key):
        log.info("news_connector: FRED key not configured — skipping FRED fetch")
        return []

    fetched_at = datetime.now(timezone.utc)
    items: list[RawMarketItem] = []

    for series in FRED_SERIES:
        series_id = series["id"]
        label = series["label"]
        unit = series["unit"]

        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,          # last 5 observations to detect trend
        }

        try:
            response = requests.get(FRED_ENDPOINT, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            log.warning("news_connector: FRED request for %s failed — %s", series_id, exc)
            continue

        observations = data.get("observations", [])
        # Filter out missing values (".")
        valid_obs = [o for o in observations if o.get("value") not in (".", "", None)]
        if not valid_obs:
            log.warning("news_connector: no valid FRED observations for %s", series_id)
            continue

        latest = valid_obs[0]
        latest_value = float(latest["value"])
        latest_date = latest.get("date", "")

        # Trend: compare latest vs 5 observations ago
        trend_str = ""
        if len(valid_obs) >= 2:
            older_value = float(valid_obs[-1]["value"])
            delta = latest_value - older_value
            trend_str = f" (recent trend: {delta:+.3f} {unit})"

        title = f"FRED: {label} = {latest_value:.3f} {unit} as of {latest_date}"
        body = (
            f"Series: {series_id}\n"
            f"Label: {label}\n"
            f"Latest Value: {latest_value:.3f} {unit}\n"
            f"As of: {latest_date}\n"
            f"{trend_str}\n"
            f"Recent observations: {[o['value'] for o in valid_obs[:5]]}"
        )

        item_id = RawMarketItem.generate_id(f"fred:{series_id}:{latest_date}")

        item = RawMarketItem(
            id=item_id,
            asset=series_id,
            market="US",
            title=title,
            body=body,
            source_name="FRED",
            source_type="macro",
            trust_tier="official",
            source_weight=1.0,
            region="US",
            timestamp=fetched_at,
            fetched_at=fetched_at,
            evidence_category="macro",
            evidence_level="official_data",
            evidence_source="fred",
            enrichment_status="complete",
            raw_metadata={
                "series_id": series_id,
                "label": label,
                "unit": unit,
                "latest_value": latest_value,
                "latest_date": latest_date,
                "observations": [
                    {"date": o["date"], "value": o["value"]}
                    for o in valid_obs[:5]
                ],
            },
        )
        items.append(item)
        log.info("news_connector: FRED %s = %.3f %s", series_id, latest_value, unit)

    log.info("news_connector: FRED returned %d macro indicators", len(items))
    return items
