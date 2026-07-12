# CLAUDE.md - Chief Market Cat

## Project Identity

CMC stands for Chief Market Cat.

CMC is a supervised market intelligence and trading decision-support system. It protects trader/investor interests first.

## Build Philosophy

- Deterministic modules first.
- LLM judgment only where useful.
- Evidence state before classification.
- Verify gate before scoring.
- Risk gate before any trade candidate.
- Human review for weak-evidence or high-impact signals.
- No autonomous live execution.

## Coding Standards

- Use concise, typed Python.
- Keep each pipeline stage independently testable.
- Prefer dataclasses and explicit schemas.
- Keep source config in YAML.
- Do not hardcode secrets or broker credentials.
- Treat all live broker actions as out of scope until explicitly approved.

## Development Notes

Use `CONTEXT.md` as the living orientation doc.

Use `docs/adr/` for durable decisions.

Use `docs/architectures/` for build specs.

