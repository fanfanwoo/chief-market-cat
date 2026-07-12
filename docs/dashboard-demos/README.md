# CMC Dashboard Demos — Globe Visualization Exploration

Two interactive demos exploring the requirement: replace email-only output with a visual dashboard where market data is correlated on a draggable, rotatable 3D globe. They are now combined behind one prototype switcher.

## Run the comparison demo

From the repository root:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/docs/dashboard-demos/`.

- `?variant=explore` opens Idea 1 directly.
- `?variant=command` opens Idea 2 directly.
- Use the floating arrows, concept buttons, or keyboard left/right arrows to switch.

Open either HTML file in a browser (internet needed for the globe library/textures). Both use the same mock signals shaped like `cmc/schemas/signals.py` (`SignalItem`: signal_type, direction, confidence, evidence/impact/urgency/liquidity scores).

## Idea 1 — Signal Globe (`01-signal-globe.html`)

The globe IS the dashboard. Full-screen, exploration-first.

- Signals plotted at their market hub; color = direction, size/height = confidence
- Animated arcs = cross-asset correlations (Brent↔WTI, SPX↔DAX, AUD↔Copper…)
- Pulse rings = high-urgency signals
- Filters: direction, min confidence, toggle arcs
- Click a point → full decision memo (thesis, invalidation, score bars, decision label)

Best for: storytelling, exploring relationships, "where is risk concentrated geographically". Weaker for: fast scanning and ranking — spatial browsing is slower than a list.

## Idea 2 — Global Command Deck (`02-global-command-deck.html`)

The globe is one component inside a trading-desk layout. Scan-first.

- Header: market regime, risk tone, signals scored, held-for-review count, portfolio VaR
- Left: market session status (open/closed exchanges), click to fly the globe there
- Center: night-earth globe with star universe, signal bars (height = watchlist score), animated correlation arcs, urgency pulse rings, session dots
- Right: ranked watchlist with score bars and decision labels; held-for-review strip
- Bottom: macro/event feed (the "what could gap me" calendar)
- **Presentation mode**: press `F` to hide left/right/bottom and go full-globe (top banner stays); click a point for its decision memo; `Esc` exits
- Scoring mirrors `cmc/pipeline/score_watchlist.py` with `config/pipeline.yaml` weights (relevance .25, evidence .25, impact .2, urgency .15, liquidity .1, confidence .05); mock signals use the `SignalItem` field names; the held signal (HSI) stays out of the ranked list, matching the verify gate

Best for: daily-brief replacement — 10-second read of regime, top signals, and event risk. Weaker for: immersion; correlations less prominent.

## Recommendation

They're not mutually exclusive: the Command Deck is the daily workflow shell; the Signal Globe is its expanded "explore" mode. If picking one to build first, start with the Command Deck — it maps 1:1 onto the pipeline output (`score_watchlist → summarize_brief → alert_human`) and protects the decision workflow (regime, held-for-review, event risk are always visible).

## Integration path (real data)

1. Add an `export_dashboard` step after `summarize_brief` that writes `data/briefs/latest.json` (signals + hub lat/lng from a small asset→hub mapping table).
2. Replace the embedded `SIGNALS` const with `fetch('../data/briefs/latest.json')`.
3. Serve locally (`python -m http.server` in the repo) or later as a small web app.
4. Correlations: start with a static asset-pair map; later compute rolling correlations in the pipeline.

Mock data throughout — no live prices, no advice, and no live trades approved. Decision labels follow project convention (Monitor only / Research deeper / Paper trade candidate / Reject).
