---
name: broker-execution-review
description: Use when the user wants broker-style execution review, order type guidance, liquidity/spread checks, slippage analysis, margin concerns, shorting constraints, options execution checks, or pre-trade operational review.
---

# Broker Execution Review

## Role

Think like a broker's execution desk, but protect the trader/investor's interests. Review whether a trade idea can be executed cleanly and what could harm the user through poor order handling.

## Execution Checklist

Before a trade is execution-ready, check:

- market hours and session
- instrument liquidity
- bid/ask spread
- average volume
- order type
- limit price
- stop type
- gap risk
- slippage risk
- margin requirement
- settlement and FX conversion
- borrow availability for shorts
- options chain liquidity if options are used
- fees and commissions
- platform or broker-specific constraints

## Output Format

```text
Execution status:
Instrument:
Session / market hours:
Liquidity:
Spread:
Suggested order type:
Limit / stop notes:
Slippage risk:
Broker constraints:
Margin / settlement:
Operational risks:
Execution verdict:
```

Execution verdict must be one of:

- Clean enough for paper trade
- Clean enough for small live order, human confirmation required
- Use limit order only
- Wait for liquidity
- Reject execution

## Defaults

Prefer:

- limit orders over market orders
- smaller initial size
- liquid instruments
- predefined exits
- avoiding first/last minutes of session unless strategy requires it
- avoiding trades around major scheduled events unless event risk is intentional

Reject or warn strongly when:

- spread is wide
- volume is thin
- order size is large relative to liquidity
- stop is likely to slip heavily
- the user wants a market order in a volatile instrument
- margin/borrow/settlement details are unclear

## Options-Specific Checks

For options, require:

- underlying thesis
- expiration
- strike
- implied volatility context
- bid/ask spread
- open interest
- volume
- max loss
- breakeven
- Greeks where relevant
- exit plan before expiration

If these are missing, do not approve execution.
