# Chief Market Cat

Chief Market Cat is a supervised market intelligence and trading decision-support system.

It starts as a deterministic pipeline for monitoring global markets and producing decision-ready briefs. It does not begin as an autonomous trading bot.

## Phase 0 Goal

Set up the project structure, domain language, schemas, configs, and first pipeline contracts before connecting real market data or broker APIs.

## Target Pipeline

```text
scheduler
-> fetch_market_data
-> fetch_news_macro
-> normalize
-> deduplicate_events
-> evidence_state
-> classify_signal
-> verify_signal
-> risk_gate
-> score_watchlist
-> summarize_brief
-> alert_human
-> journal_store
```

## Build Principle

CSC finds external strategic signals.
CDC finds internal customer signals.
CMC finds market signals, but Risk Guardian decides whether they are tradable.

## Project Instruction Assets

- `docs/agent-instructions/` contains ChatGPT Project instructions and Claude-style skills.
- `docs/architectures/blue-sky-architecture-roadmap.md` contains the ideal-state architecture and roadmap.
- `docs/images/` contains the rendered architecture diagrams.
