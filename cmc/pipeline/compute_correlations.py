"""Compute real return correlations for the watchlist and cache them.

Reuses the same data source as the rest of the pipeline (yfinance daily
closes). The dashboard reads the cached result and falls back to the structural
prior in ``generate_dashboard.STRUCTURAL_CORR`` when no fresh cache exists.

Design (deterministic module, no LLM):
    fetch daily closes → daily % returns → rolling-window Pearson correlation
    → keep pairs with |r| >= min_abs_r → cache to disk with window + timestamp.

IMPORTANT: correlations are regime-dependent and unstable — they spike toward
+1 in a sell-off. The cached payload always records the lookback window and the
generation time so the dashboard can label the arcs honestly ("120d returns").
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "dashboard" / "correlations_cache.json"

DEFAULTS = {
    "lookback_days": 120,   # trading days in the correlation window
    "min_abs_r": 0.30,      # drop weak pairs to keep the globe readable
    "cache_max_age_hours": 36,
}


def _corr_cfg(cfg: dict) -> dict:
    """Read correlation settings, merged over defaults. The block lives in
    pipeline.yaml, so load_config() nests it under cfg["pipeline"]."""
    block = cfg.get("pipeline", {}).get("correlations", {}) or {}
    return {**DEFAULTS, **block}


def _watchlist_symbols(cfg: dict) -> list[str]:
    watchlist = cfg.get("sources", {}).get("watchlist", {}) or {}
    symbols: list[str] = []
    for market_symbols in watchlist.values():
        symbols.extend(market_symbols)
    return symbols


def _fetch_returns(symbols: list[str]):
    """Fetch ~1y of daily closes via yfinance and return a daily-return
    DataFrame (one column per symbol). Isolated so it can be mocked in tests.
    Returns None on any failure (e.g. no network)."""
    try:
        import yfinance as yf  # lazy import, mirrors market_data_connector
    except ImportError:
        log.warning("compute_correlations: yfinance not installed — skipping")
        return None

    try:
        raw = yf.download(
            symbols, period="1y", interval="1d",
            auto_adjust=True, progress=False, threads=True,
        )
        if raw is None or raw.empty:
            log.warning("compute_correlations: empty price frame — skipping")
            return None
        # Multi-symbol download → columns are a ("Close", SYMBOL) MultiIndex.
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
        returns = close.pct_change().dropna(how="all")
        return returns
    except Exception as e:  # network / parsing / rate-limit
        log.warning("compute_correlations: fetch failed (%s) — skipping", type(e).__name__)
        return None


def _corr_links_from_returns(returns, min_abs_r: float, lookback_days: int) -> list[list]:
    """Pure function: daily-return DataFrame → signed correlation links.
    Kept side-effect-free so it can be unit-tested without any network."""
    window = returns.tail(lookback_days)
    corr = window.corr(min_periods=max(20, lookback_days // 4))  # Pearson
    cols = list(corr.columns)
    links: list[list] = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if r is None:
                continue
            try:
                rf = float(r)
            except (TypeError, ValueError):
                continue
            if rf != rf:  # NaN (insufficient overlap)
                continue
            if abs(rf) >= min_abs_r:
                links.append([cols[i], cols[j], round(rf, 2)])
    # Strongest first so the densest arcs draw on top
    links.sort(key=lambda x: abs(x[2]), reverse=True)
    return links


def compute_and_cache(cfg: dict, force: bool = False) -> dict | None:
    """Fetch, compute, and cache correlations. Returns the cache payload or
    None if data was unavailable (caller falls back to the structural prior).

    If a fresh cache already exists it is reused and NO download happens, so the
    freshness window (cache_max_age_hours) actually saves work. Pass force=True
    to bypass the cache and re-fetch."""
    if not force:
        cached = load_correlations(cfg)
        if cached is not None:
            log.info("compute_correlations: reusing fresh cache (%d links)",
                     len(cached.get("links", [])))
            return cached

    corr_cfg = _corr_cfg(cfg)
    symbols = _watchlist_symbols(cfg)
    if not symbols:
        return None

    returns = _fetch_returns(symbols)
    if returns is None or returns.shape[0] < 20:
        return None

    links = _corr_links_from_returns(
        returns, corr_cfg["min_abs_r"], corr_cfg["lookback_days"]
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": corr_cfg["lookback_days"],
        "min_abs_r": corr_cfg["min_abs_r"],
        # Recorded so load_correlations() can detect a config/watchlist change
        # and invalidate the cache even if it's still within its age window.
        "symbols": sorted(symbols),
        "source": "yfinance_returns",
        "links": links,
    }
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("compute_correlations: cached %d links → %s", len(links), CACHE_PATH.name)
    except OSError as e:
        log.warning("compute_correlations: could not write cache (%s)", e)
    return payload


def load_correlations(cfg: dict) -> dict | None:
    """Return the cached payload if present, fresh, AND still built from the
    current config + watchlist — else None. A payload computed under an old
    min_abs_r/lookback_days or a since-changed watchlist is treated the same
    as a stale one, even if it's within cache_max_age_hours."""
    corr_cfg = _corr_cfg(cfg)
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        payload.get("window_days") != corr_cfg["lookback_days"]
        or payload.get("min_abs_r") != corr_cfg["min_abs_r"]
    ):
        log.info("compute_correlations: cache config changed — ignoring")
        return None
    if payload.get("symbols") != sorted(_watchlist_symbols(cfg)):
        log.info("compute_correlations: watchlist changed — ignoring cache")
        return None
    try:
        age_h = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(payload["generated_at"])
        ).total_seconds() / 3600.0
    except (KeyError, ValueError):
        return None
    if age_h > corr_cfg["cache_max_age_hours"]:
        log.info("compute_correlations: cache stale (%.1fh) — ignoring", age_h)
        return None
    return payload
