---
name: market-intelligence
description: Use when the user wants global market monitoring, daily market briefs, signal classification, watchlist ranking, macro/news interpretation, or an external intelligence pipeline similar to CSC for trading.
---

# Market Intelligence

## Role

Turn noisy global market information into structured, decision-ready intelligence. This is a monitoring and research skill, not an execution skill.

## CSC-Inspired Pipeline

Use this mental model:

```text
fetch_market_data
-> fetch_news_macro
-> normalize
-> deduplicate_events
-> evidence_state
-> classify_signal
-> verify_signal
-> score_watchlist
-> summarize_brief
-> alert_human
```

Keep deterministic steps deterministic. Use LLM judgment only for interpretation, classification, summarization, and hypothesis generation.

## Signal Schema

Represent market signals in structured form:

```json
{
  "asset": "",
  "market": "",
  "timeframe": "",
  "signal_type": "",
  "direction": "",
  "evidence": [],
  "evidence_level": "strong|moderate|weak|headline_only",
  "confidence": "low|medium|high",
  "risk_flags": [],
  "invalidation": "",
  "decision": "monitor|research|paper_trade_candidate|reject"
}
```

## Evidence Tiers

- Strong: official filings, central bank/regulator data, confirmed company releases, full market data.
- Moderate: reputable publisher with details, corroborated price/volume behavior, multiple independent sources.
- Weak: single publisher, thin data, social sentiment, unverified commentary.
- Headline only: cannot support high-impact conclusions.

Headline-only high-impact claims must be held for human review.

## Signal Types

Classify signals as one of:

- trend_continuation
- breakout
- mean_reversion
- volatility_expansion
- volatility_compression
- macro_regime_shift
- earnings_event
- policy_event
- liquidity_stress
- sentiment_dislocation
- no_trade_unclear

## Daily Brief

Use this format:

```text
Market regime:
Risk tone:
Key global moves:
Macro calendar:
Volatility:
Cross-asset confirmation:
Top signals:
Held-for-review signals:
Watchlist changes:
Trader implications:
No-trade zones:
```

## Verification Gate

Hold a signal for review if:

- evidence is weak and claimed impact is high
- source is headline-only
- data is stale
- price move is illiquid
- event risk is near
- signal conflicts with portfolio risk
- LLM inference goes beyond evidence

Pass a signal only if evidence, context, and risk are explicit.
