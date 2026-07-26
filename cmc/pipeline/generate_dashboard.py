"""Generate the live Global Command Deck dashboard.

Reads docs/dashboard-demos/02-global-command-deck.html as a template,
replaces the hardcoded JS data constants (SIGNALS, HELD, SESSIONS,
EVENTS, CORRELATIONS) with real pipeline output, and writes a
self-contained HTML file to data/dashboard/dashboard_YYYY-MM-DD.html.

No server needed — just open the file in a browser.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from cmc.schemas.signals import ScoredSignal, SignalItem
from cmc.pipeline import compute_correlations

log = logging.getLogger(__name__)

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs" / "dashboard-demos" / "02-global-command-deck.html"
)
DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "data" / "dashboard"

# ── Geographic lookup for the 16 watchlist symbols ────────────────────────────
# lat/lng is the exchange city, not the company HQ.
SYMBOL_GEO: dict[str, dict] = {
    "AAPL":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "MSFT":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "NVDA":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "AMZN":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "GOOGL":  {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "META":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "TSLA":   {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities"},
    "SPY":    {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "US equities (ETF)"},
    "QQQ":    {"lat": 41.88, "lng": -87.63, "hub": "Chicago (CME)", "market": "US equities (ETF)"},
    "GLD":    {"lat": 40.71, "lng": -74.00, "hub": "New York",      "market": "Metals (ETF)"},
    "CBA.AX": {"lat": -33.87, "lng": 151.21, "hub": "Sydney",       "market": "ASX financials"},
    "BHP.AX": {"lat": -33.86, "lng": 151.20, "hub": "Sydney",       "market": "ASX materials"},
    "RIO.AX": {"lat": -33.85, "lng": 151.22, "hub": "Sydney",       "market": "ASX materials"},
    "WBC.AX": {"lat": -33.88, "lng": 151.19, "hub": "Sydney",       "market": "ASX financials"},
    "ANZ.AX": {"lat": -33.89, "lng": 151.21, "hub": "Sydney",       "market": "ASX financials"},
    "NAB.AX": {"lat": -33.87, "lng": 151.23, "hub": "Sydney",       "market": "ASX financials"},
}

# ── Exchange sessions (approximate UTC open/close hours, weekdays only) ───────
_SESSIONS_CONFIG = [
    {"ex": "NYSE / Nasdaq", "city": "New York",  "lat": 40.71,  "lng": -74.00, "utc_open": 13, "utc_close": 20},
    {"ex": "CME",           "city": "Chicago",   "lat": 41.88,  "lng": -87.63, "utc_open": 13, "utc_close": 20},
    {"ex": "B3",            "city": "São Paulo", "lat": -23.55, "lng": -46.63, "utc_open": 13, "utc_close": 20},
    {"ex": "LSE / ICE",     "city": "London",    "lat": 51.51,  "lng": -0.13,  "utc_open": 8,  "utc_close": 16},
    {"ex": "Xetra",         "city": "Frankfurt", "lat": 50.11,  "lng": 8.68,   "utc_open": 7,  "utc_close": 15},
    {"ex": "SIX",           "city": "Zurich",    "lat": 47.37,  "lng": 8.54,   "utc_open": 7,  "utc_close": 15},
    {"ex": "NSE",           "city": "Mumbai",    "lat": 19.08,  "lng": 72.88,  "utc_open": 3,  "utc_close": 10},
    {"ex": "SGX",           "city": "Singapore", "lat": 1.35,   "lng": 103.82, "utc_open": 1,  "utc_close": 9},
    {"ex": "SSE / SHFE",    "city": "Shanghai",  "lat": 31.23,  "lng": 121.47, "utc_open": 1,  "utc_close": 7},
    {"ex": "HKEX",          "city": "Hong Kong", "lat": 22.32,  "lng": 114.17, "utc_open": 1,  "utc_close": 8},
    {"ex": "TSE",           "city": "Tokyo",     "lat": 35.68,  "lng": 139.69, "utc_open": 0,  "utc_close": 6},
    {"ex": "ASX",           "city": "Sydney",    "lat": -33.87, "lng": 151.21, "utc_open": 0,  "utc_close": 6},
]


def generate_dashboard(
    scored: list[ScoredSignal],
    held: list[SignalItem],
    macro_items: list,
    cfg: dict,
) -> Path | None:
    """
    Generate the live dashboard HTML from real pipeline data.

    Returns the path to the generated file, or None if the template is missing.
    """
    if not TEMPLATE_PATH.exists():
        log.warning("generate_dashboard: template not found at %s — skipping", TEMPLATE_PATH)
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc)

    # Build each JS data constant
    signals_js = _build_signals_js(scored)
    held_js = _build_held_js(held)
    sessions_js = _build_sessions_js(now_utc)
    events_js = _build_events_js(macro_items, today)
    # Correlations: prefer real return correlation (cached by the
    # compute_correlations stage); fall back to the structural prior. Only
    # pairs where BOTH assets have a signal today are emitted, so every arc
    # connects two live nodes on the globe.
    corr_links, corr_label = _resolve_correlations(scored, cfg)
    correlations_js = json.dumps(corr_links, indent=1)

    # Load template and substitute
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = _replace_js_const(html, "SIGNALS", signals_js)
    html = _replace_js_const(html, "HELD", held_js)
    html = _replace_js_const(html, "SESSIONS", sessions_js)
    html = _replace_js_const(html, "EVENTS", events_js)
    html = _replace_js_const(html, "CORRELATIONS", correlations_js)

    # Label the arc legend with the actual correlation source/window (honest
    # about whether arcs are price-derived or the structural fallback).
    html = html.replace(
        "arc = correlation (blue together · amber inverse)",
        f"arc = {corr_label} (blue together · amber inverse)",
    )

    # Update static text in the header
    html = html.replace(
        "Demo run · mock data · not financial advice",
        f"Run: {today} · live data · not financial advice",
    )
    html = html.replace(
        "<title>CMC · Global Command Deck</title>",
        f"<title>CMC · Command Deck · {today}</title>",
    )

    # Update market regime + risk tone KPIs from FRED data
    regime, tone, tone_color = _infer_regime(macro_items)
    html = html.replace("<b>Risk-on, fragile</b>", f"<b>{regime}</b>")
    html = html.replace(
        '<b style="color:var(--unclear)">Cautious</b>',
        f'<b style="color:{tone_color}">{tone}</b>',
    )

    # Save
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DASHBOARD_DIR / f"dashboard_{today}.html"
    out_path.write_text(html, encoding="utf-8")
    log.info("generate_dashboard: saved → %s", out_path)
    return out_path


# ── Data builders ──────────────────────────────────────────────────────────────

def _build_signals_js(scored: list[ScoredSignal]) -> str:
    items = []
    for s in scored:
        geo = SYMBOL_GEO.get(s.asset, {
            "lat": 0.0, "lng": 0.0,
            "hub": "Global",
            "market": s.market or "Unknown",
        })
        items.append({
            "id": f"sig-{s.asset.lower().replace('.', '-')}",
            "asset": s.asset,
            "market": geo["market"],
            "region": _region_from_hub(geo["hub"]),
            "hub": geo["hub"],
            "lat": geo["lat"],
            "lng": geo["lng"],
            "signal_type": s.signal_type,
            "direction": _direction(s.direction),
            "confidence": round(s.confidence, 2),
            # watchlist_score drives bar height on the globe + side panel.
            # Fall back to confidence if the scorer left it at 0 so bars are
            # never flat when a real signal exists.
            "watchlist_score": round(s.watchlist_score or s.confidence, 2),
            "relevance_score": round(s.relevance_score, 2),
            "evidence_score": round(s.evidence_score, 2),
            "impact_score": round(s.impact_score, 2),
            "urgency_score": round(s.urgency_score, 2),
            "liquidity_score": round(s.liquidity_score, 2),
            "thesis": s.rationale or "No rationale provided.",
            "invalidation": s.invalidation or "Not specified.",
            "decision": _decision(s.confidence, s.signal_type),
        })
    return json.dumps(items, indent=1)


def _build_held_js(held: list[SignalItem]) -> str:
    items = [
        {"asset": h.asset, "reason": h.human_review_reason or "held for review"}
        for h in held
    ]
    return json.dumps(items, indent=1)


def _build_sessions_js(now_utc: datetime) -> str:
    hour = now_utc.hour
    sessions = []
    for s in _SESSIONS_CONFIG:
        o, c = s["utc_open"], s["utc_close"]
        # Handle sessions that wrap midnight (e.g. Tokyo 0–6 UTC)
        if o <= c:
            is_open = o <= hour < c
        else:
            is_open = hour >= o or hour < c
        sessions.append({
            "ex": s["ex"], "city": s["city"],
            "lat": s["lat"], "lng": s["lng"],
            "open": is_open,
        })
    return json.dumps(sessions, indent=1)


def _build_events_js(macro_items: list, today: str) -> str:
    events = []
    for item in macro_items:
        raw = getattr(item, "raw_metadata", {}) or {}
        label = raw.get("label") or getattr(item, "asset", "Macro")
        value = raw.get("latest_value")
        unit = raw.get("unit", "")
        date = raw.get("latest_date", "recent")
        if value is not None:
            # Include a simple trend indicator
            obs = raw.get("observations", [])
            trend = ""
            if len(obs) >= 2:
                try:
                    delta = float(obs[0]["value"]) - float(obs[-1]["value"])
                    trend = f" (trend: {delta:+.2f})"
                except (KeyError, ValueError, TypeError):
                    pass
            events.append({
                "t": f"As of {date}",
                "p": f"{label}: {value:.3f} {unit}{trend}",
                "s": "macro · FRED",
            })
    events.append({
        "t": f"Today {today}",
        "p": "CMC daily brief generated — open data/briefs/ for full report",
        "s": "system · CMC",
    })
    return json.dumps(events, indent=1)


# ── Structural correlation prior ────────────────────────────────────────────────
# Hand-specified structural relationships among the 16 watchlist symbols.
# These are NOT computed from price history — they encode well-known co-movement
# clusters (mega-cap tech, ASX financials, ASX materials, gold vs. risk) so the
# globe can draw correlation arcs before a live price feed exists. Replace with
# rolling return correlation once price history is available. Values are signed
# structural strengths in [-1, 1].
STRUCTURAL_CORR: list[tuple[str, str, float]] = [
    # US mega-cap tech / broad-market cluster
    ("SPY", "QQQ", 0.95), ("AAPL", "QQQ", 0.88), ("MSFT", "QQQ", 0.90),
    ("NVDA", "QQQ", 0.85), ("AAPL", "MSFT", 0.82), ("MSFT", "NVDA", 0.78),
    ("AAPL", "SPY", 0.85), ("MSFT", "SPY", 0.83), ("NVDA", "SPY", 0.72),
    ("AMZN", "QQQ", 0.80), ("META", "QQQ", 0.78), ("GOOGL", "META", 0.72),
    ("TSLA", "QQQ", 0.62),
    # ASX financials cluster
    ("CBA.AX", "WBC.AX", 0.90), ("CBA.AX", "ANZ.AX", 0.88), ("CBA.AX", "NAB.AX", 0.89),
    ("WBC.AX", "ANZ.AX", 0.91), ("WBC.AX", "NAB.AX", 0.90), ("ANZ.AX", "NAB.AX", 0.92),
    # ASX materials / global growth
    ("BHP.AX", "RIO.AX", 0.88), ("BHP.AX", "SPY", 0.50), ("RIO.AX", "SPY", 0.48),
    # Cross-region equity beta
    ("SPY", "CBA.AX", 0.45),
    # Gold vs. risk (inverse)
    ("GLD", "SPY", -0.28), ("GLD", "QQQ", -0.24),
]


def _sig_id(asset: str) -> str:
    """Match the id scheme used in _build_signals_js."""
    return f"sig-{asset.lower().replace('.', '-')}"


def _resolve_correlations(
    scored: list[ScoredSignal], cfg: dict
) -> tuple[list[list], str]:
    """Return (arc_links, source_label).

    Prefers real return correlation cached by the compute_correlations stage;
    falls back to the structural prior when no fresh cache exists. Only pairs
    where BOTH assets have a signal today are emitted, so every arc connects two
    live globe nodes.

    Signed values are kept: the template renders positive correlations blue
    ("move together") and negative ones amber ("inverse"), scaling opacity/width
    by magnitude. Inverse links (e.g. GLD vs. SPY) are often the most useful on
    the map because they flag hedges/diversification.
    """
    present = {s.asset for s in scored}

    payload = compute_correlations.load_correlations(cfg)
    if payload and payload.get("links"):
        source_pairs = payload["links"]  # [[sym, sym, r], ...] from prices
        label = f"{payload.get('window_days', '?')}d return correlation"
    else:
        source_pairs = [[a, b, r] for a, b, r in STRUCTURAL_CORR]
        label = "structural correlation"

    links = [
        [_sig_id(a), _sig_id(b), round(float(r), 2)]
        for a, b, r in source_pairs
        if a in present and b in present
    ]
    return links, label


# ── Helpers ────────────────────────────────────────────────────────────────────

def _replace_js_const(html: str, name: str, value: str) -> str:
    """Replace `const NAME = [...];` (including multiline) in the HTML."""
    pattern = rf"const {re.escape(name)} = \[.*?\];"
    replacement = f"const {name} = {value};"
    # Use a callable replacement so backslashes in the JSON payload (e.g. \u
    # escapes) are inserted literally instead of parsed as regex escapes.
    new_html, n = re.subn(pattern, lambda _m: replacement, html, flags=re.DOTALL)
    if n == 0:
        log.warning("generate_dashboard: marker 'const %s = [...]' not found in template", name)
    return new_html


def _direction(raw: str) -> str:
    return {"bullish": "long", "bearish": "short"}.get((raw or "").lower(), "unclear")


def _decision(confidence: float, signal_type: str) -> str:
    if signal_type == "no_trade_unclear":
        return "Monitor only"
    if confidence >= 0.70:
        return "Paper trade candidate"
    if confidence >= 0.60:
        return "Research deeper"
    return "Monitor only"


def _region_from_hub(hub: str) -> str:
    h = hub.lower()
    if "sydney" in h:
        return "asia"
    if any(x in h for x in ("new york", "chicago")):
        return "us"
    if any(x in h for x in ("london", "frankfurt", "zurich")):
        return "europe"
    if any(x in h for x in ("tokyo", "shanghai", "hong kong", "singapore", "mumbai")):
        return "asia"
    if any(x in h for x in ("são paulo", "sao paulo")):
        return "latam"
    return "global"


def _infer_regime(macro_items: list) -> tuple[str, str, str]:
    """Return (regime_text, tone_text, tone_css_color) from FRED data."""
    vix = us10y = fed_funds = None
    for item in macro_items:
        raw = getattr(item, "raw_metadata", {}) or {}
        sid = raw.get("series_id", "")
        val = raw.get("latest_value")
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if sid == "VIXCLS":
            vix = val
        elif sid == "DGS10":
            us10y = val
        elif sid == "FEDFUNDS":
            fed_funds = val

    if vix is not None and vix > 25:
        return "Risk-off, elevated vol", "Defensive", "var(--short)"
    if vix is not None and vix > 18:
        return "Transitioning, caution", "Cautious", "var(--unclear)"
    if us10y is not None and us10y > 4.5:
        return "Risk-on, rate headwinds", "Cautious", "var(--unclear)"
    if macro_items:
        return "Risk-on, constructive", "Neutral–positive", "var(--long)"
    return "Risk-on, fragile", "Cautious", "var(--unclear)"
