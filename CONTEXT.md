# CONTEXT

The single living orientation doc for Chief Market Cat. Read this first.

When this doc and code disagree, the code wins. Update this doc after meaningful changes.

_Last updated: 2026-07-08. Stage: MVP 1 active._

## What CMC Is

Chief Market Cat is a supervised global market intelligence and trading decision-support system.

It monitors market, news, macro, portfolio, and broker-state signals, then turns them into structured watchlist items, trade decision memos, and human review queues.

It is not an autonomous trading bot.

## Current State

MVP 1 is active.

The project has MVP 1 plumbing for market/news/macro intake, evidence labeling,
classification fallback, verification, risk gating, watchlist scoring, and brief
generation. Real API-backed providers still require `SETUP.md` credentials and
dependencies before live runs.

New presentation requirement: MVP 1 output should be human-friendly, not only
email or Markdown. Add a local dashboard that reads persisted structured run
data and presents market regime, risk tone, top signals, held-for-review items,
risk-blocked items, and watchlist scores.

New spatial exploration requirement: evaluate a draggable, rotatable global view
that plots market signals by hub and draws cross-asset relationships between
regions. The globe may be the primary exploration surface or an expanded view
inside the review dashboard; the dashboard must still keep evidence, rankings,
review holds, and the no-live-trades boundary easy to inspect.

No live execution exists. The default runner does not place broker orders or log
automatic paper trades.

Project-level agent instructions now live in `docs/agent-instructions/`.
Architecture images live in `docs/images/`.

## Tracing

Two layers, deliberately separate (see `docs/adr/0001-langsmith-tracing-boundary.md`):

- `cmc/eval/tracing.py` — local `@trace` / `span()` harness writing
  `data/eval/traces.jsonl`. Full fidelity, never leaves the machine.
- `cmc/eval/langsmith_tracing.py` — optional remote export for
  `classify_signal`. Allowlisted fields only, no secrets, no free text, no
  `cfg`. Off unless `CMC_LANGSMITH_TRACING=1` and `LANGSMITH_API_KEY` are set.
  Install with `pip install -e '.[tracing]'`. One controlled trace:
  `python3 scripts/trace_one_classification.py`.

## Target Pipeline

```text
scheduler -> fetch_market_data -> fetch_news_macro -> normalize
          -> deduplicate_events -> evidence_state -> classify_signal
          -> verify_signal -> risk_gate -> score_watchlist
          -> summarize_brief -> alert_human -> journal_store
```

## Agent Roles

Blue-sky architecture has 8 roles:

1. Market Data Agent
2. News + Macro Agent
3. Signal Classifier Agent
4. Evidence Verification Agent
5. Strategy Hypothesis Agent
6. Portfolio Manager Agent
7. Risk Guardian Agent
8. Execution + Journal Agent

In early phases, these remain deterministic modules where possible. Promote a module to an agent only when it must choose, retry, coordinate, verify, escalate, or loop.

## Phase Pins

### MVP 1

Market intelligence brief only.

Outputs:

- local dashboard for reviewing run results
- draggable global signal and correlation view
- market regime
- risk tone
- top global moves
- top structured signals
- held-for-review signals
- watchlist changes
- no-trade warnings
- saved Markdown/email brief as backup delivery

Excluded:

- live trading
- autonomous execution
- leverage recommendations
- options execution

### Day 2

Evidence and risk gates.

Build:

- evidence_state
- verify_signal
- risk_gate
- review_queue
- decision journal

Excluded:

- live execution
- autonomous broker actions
- complex multi-agent orchestration

## Safety Boundary

No live trading without all of:

- explicit human approval
- written risk framework
- broker execution review
- max-loss cap
- kill switch
- audit log

## Project Instruction Assets

- `docs/agent-instructions/chatgpt-project-instructions.md` — master instruction for a ChatGPT Project.
- `docs/agent-instructions/claude-skills/` — Claude/Codex-style skill folders.
- `docs/architectures/blue-sky-architecture-roadmap.md` — ideal-state architecture, roadmap, and pipeline.
- `docs/images/` — rendered architecture diagrams.
