# Phase 0 Scaffold

## Purpose

Create a project home for Chief Market Cat before implementation begins.

Status update: Phase 0 is complete. The project has moved to MVP 1 active.

## Included

- living context docs
- config files
- schema modules
- connector modules
- pipeline modules
- prompt placeholders
- storage module
- data folders
- tests folder

## Not Included

- real data providers
- broker API calls
- LLM calls
- paper trading
- live execution

## Next Build Step

Define the first concrete data contract and implement a manual-input MVP run:

```text
manual source items -> normalize -> evidence_state -> verify_signal -> brief
```

Current MVP 1 build step:

```text
fetch_market_data -> fetch_news_macro -> normalize -> deduplicate_events
-> evidence_state -> classify_signal -> verify_signal -> risk_gate
-> score_watchlist -> summarize_brief -> alert_human -> journal_store
-> persist structured run data -> local dashboard
```

New output requirement:

- Email/Markdown briefs remain useful backup delivery.
- MVP 1 should also provide a local dashboard for human-friendly review.
- The dashboard should show market regime, risk tone, top signals,
  held-for-review items, risk-blocked items, watchlist scores, and the safety
  boundary that no live trades are approved.
