# How To Use This Trading Agent Instruction Pack

## ChatGPT Project

Paste the full contents of:

```text
trading-agent-instructions/chatgpt-project-instructions.md
```

into the ChatGPT Project instructions.

Use the project for:

- market briefs
- trade idea review
- portfolio review
- risk checks
- broker/execution checks
- trading journal review
- building the trading-agent system

## Claude / Codex-Style Skills

Each folder under:

```text
trading-agent-instructions/claude-skills/
```

is a standalone skill folder with a `SKILL.md`.

Use:

- `trading-manager` for general market, trade, and portfolio decisions
- `market-intelligence` for global market monitoring and signal briefs
- `risk-guardian` before approving any trade idea
- `broker-execution-review` before thinking about order placement
- `trading-journal-coach` after trades or during performance review

## Recommended Skill Order

For a trade idea:

```text
market-intelligence
-> trading-manager
-> risk-guardian
-> broker-execution-review
-> trading-journal-coach after exit
```

For system building:

```text
market-intelligence
-> risk-guardian
-> trading-manager
```

## Important Boundary

These instructions are for decision support, research, risk management, and education. They should not be used to authorize autonomous live trading. Live trades require human approval and a written risk framework.
