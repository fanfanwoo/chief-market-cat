# ADR 0001 — Redacted LangSmith boundary for classify_signal

Status: accepted — 2026-08-08

## Context

We want to learn from classifier behaviour over time (which evidence levels lead
to which signal types, where confidence sits, how often we fall back). LangSmith
is a third-party service, so anything traced leaves the machine.

`cfg` carries `config/secrets.yaml` — Gemini/NewsAPI/FRED keys, Gmail app
password, sender/recipient addresses, Alpaca credentials. Item text carries
headlines and article bodies. None of that may be transmitted.

We already have `cmc/eval/tracing.py`, a local JSONL trace harness.

## Decision

1. Two tracing layers, distinct on purpose:
   - `cmc/eval/tracing.py` — local, full fidelity, never leaves disk.
   - `cmc/eval/langsmith_tracing.py` — remote, allowlist-only.
   The second is not a replacement for the first; it is the redaction boundary.
2. No decorator on any function that receives `cfg`. The classifier calls
   `build_input_payload(item, model_name)` / `build_output_payload(signal, ...)`
   and hands two plain dicts to `emit_classification`. `cfg` never crosses.
3. Field allowlists (`ALLOWED_INPUT_FIELDS`, `ALLOWED_OUTPUT_FIELDS`) are the
   contract. Payloads are built by naming fields explicitly, then re-filtered
   against the allowlist before send.
4. Free text never leaves: titles, bodies, prompts, rationale, and invalidation
   become character counts. Exception messages become a category
   (`rate_limit`, `auth_error`, ...) because Gemini errors can embed request
   URLs, keys, and prompt fragments.
5. Off by default. Requires `CMC_LANGSMITH_TRACING=1` **and** `LANGSMITH_API_KEY`.
   `langsmith` is an optional extra; the import is lazy.
6. Tracing failures are swallowed. The classifier result is identical whether
   tracing is on, off, or broken.

## Consequences

- Traces show shape, not content. Debugging a bad classification still needs the
  local `traces.jsonl` or the run journal.
- Adding a traced field is a deliberate, reviewable edit to the allowlist.
- Tests (`tests/test_langsmith_tracing.py`) assert on the exact payload a sink
  would transmit, so redaction is enforced offline with no network.
