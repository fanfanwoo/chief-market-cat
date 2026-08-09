"""Redacted LangSmith export for the signal-classification stage.

── How this relates to `cmc/eval/tracing.py` ──────────────────────────────
    cmc/eval/tracing.py            cmc/eval/langsmith_tracing.py
    ---------------------------    -----------------------------------------
    local dev harness              remote export
    writes data/eval/traces.jsonl  posts runs to LangSmith
    captures whatever you pass it  only the allowlisted fields below
    never leaves the machine       leaves the machine → must be redacted
    @trace / span() decorators     no decorators on config-carrying functions

They are not duplicates and neither replaces the other: `tracing.py` stays the
full-fidelity local record (safe because it never leaves disk), this module is
the narrow, auditable window onto a third-party service. Nothing in this module
reads `cfg`, `config/secrets.yaml`, or `os.environ` beyond the two switches in
`is_enabled()`, so a secret cannot reach LangSmith by accident.

What LangSmith receives is fully described by `ALLOWED_INPUT_FIELDS` and
`ALLOWED_OUTPUT_FIELDS`. Payloads are built by explicitly naming fields, then
filtered against those allowlists again before send — belt and braces.

Enable:   export CMC_LANGSMITH_TRACING=1 and export LANGSMITH_API_KEY=...
Disable:  unset CMC_LANGSMITH_TRACING (the default; no network, no imports)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

RUN_NAME = "cmc.classify_signal"
RUN_TYPE = "chain"
BASE_TAGS = ("cmc", "stage:classify_signal")

ENABLE_ENV = "CMC_LANGSMITH_TRACING"
API_KEY_ENV = "LANGSMITH_API_KEY"

# Longest string value that may be transmitted. Every allowlisted string field is
# a short enum-like token (asset, direction, ...), so this is a backstop only.
MAX_STR_CHARS = 64

# ── The complete set of fields that may leave this machine ──────────────────
ALLOWED_INPUT_FIELDS = frozenset({
    "item_id",             # sha256 prefix, already non-reversible
    "asset",
    "market",
    "region",
    "timeframe",
    "source_type",
    "trust_tier",
    "evidence_level",
    "evidence_category",
    "model",
    "has_price_data",
    "title_chars",
    "body_chars",
    "macro_context_lines",
    "item_age_hours",
})

ALLOWED_OUTPUT_FIELDS = frozenset({
    "outcome",             # classified | fallback | error
    "fallback_category",   # sanitized category, never an error message
    "signal_type",
    "direction",
    "confidence",
    "human_review_flag",
    "relevance_score",
    "evidence_score",
    "impact_score",
    "urgency_score",
    "liquidity_score",
    "has_invalidation",
    "rationale_chars",
    "latency_ms",
})

# Explicitly never transmitted: cfg / cfg["secrets"], any *_key / *_password /
# gmail_* value, os.environ, raw prompts, titles, bodies, rationale text,
# invalidation text, raw_metadata, exception messages, URLs, file paths.

TraceSink = Callable[[dict], None]
_sink: TraceSink | None = None      # None → the real LangSmith sink
_client: Any = None                 # lazily-created langsmith.Client


def is_enabled() -> bool:
    """True only when the operator opted in AND a LangSmith key is present."""
    flag = os.environ.get(ENABLE_ENV, "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return bool(os.environ.get(API_KEY_ENV, "").strip())


def set_sink(sink: TraceSink | None) -> None:
    """Swap the transport (tests inject a capturing sink). None restores LangSmith."""
    global _sink
    _sink = sink


def _scrub(value: Any) -> Any:
    """Coerce an allowlisted value into a small, JSON-safe primitive."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    return text if len(text) <= MAX_STR_CHARS else text[:MAX_STR_CHARS]


def _filter(payload: dict, allowed: frozenset[str]) -> dict:
    """Drop anything not on the allowlist, then scrub what survives."""
    return {k: _scrub(v) for k, v in payload.items() if k in allowed}


def error_category(exc: BaseException) -> str:
    """Map an exception to a coarse category. The message itself is never used —
    Gemini errors can embed request URLs, keys, and prompt text.

    Defensive: a pathological exception whose __str__ raises must not take the
    pipeline down, so classification of the category is itself fail-open."""
    try:
        return _error_category(exc)
    except Exception:  # noqa: BLE001
        return "unknown_error"


def _error_category(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "exhausted" in msg or "rate limit" in msg:
        return "rate_limit"
    if "permission" in msg or "unauthenticated" in msg or "api key" in msg or "401" in msg or "403" in msg:
        return "auth_error"
    if "deadline" in msg or "timeout" in msg or "timed out" in msg:
        return "timeout"
    if isinstance(exc, ValueError) and "json" in name.lower():
        return "parse_error"
    if name in ("JSONDecodeError", "KeyError", "AttributeError", "TypeError"):
        return "response_parse_error"
    if "connection" in msg or "network" in msg or "unavailable" in msg or "503" in msg:
        return "network_error"
    return "unknown_error"


def build_input_payload(item: Any, model_name: str | None, macro_context_lines: int = 0) -> dict:
    """Allowlisted view of one normalized item. Never touches cfg or raw text."""
    raw = getattr(item, "raw_metadata", None) or {}
    body = getattr(item, "body", "") or ""
    title = getattr(item, "title", "") or ""
    payload = {
        "item_id": getattr(item, "id", None),
        "asset": getattr(item, "asset", None),
        "market": getattr(item, "market", None),
        "region": getattr(item, "region", None),
        "timeframe": getattr(item, "timeframe", None),
        "source_type": getattr(item, "source_type", None),
        "trust_tier": getattr(item, "trust_tier", None),
        "evidence_level": getattr(item, "evidence_level", None),
        "evidence_category": getattr(item, "evidence_category", None),
        "model": model_name,
        "has_price_data": raw.get("price") is not None,
        "title_chars": len(title),
        "body_chars": len(body),
        "macro_context_lines": macro_context_lines,
        "item_age_hours": _age_hours(getattr(item, "timestamp", None)),
    }
    return _filter(payload, ALLOWED_INPUT_FIELDS)


def build_output_payload(
    signal: Any,
    *,
    outcome: str,
    latency_ms: float,
    fallback_category: str | None = None,
) -> dict:
    """Allowlisted view of one classification result. Text fields become lengths."""
    rationale = getattr(signal, "rationale", "") or ""
    payload = {
        "outcome": outcome,
        "fallback_category": fallback_category,
        "signal_type": getattr(signal, "signal_type", None),
        "direction": getattr(signal, "direction", None),
        "confidence": getattr(signal, "confidence", None),
        "human_review_flag": bool(getattr(signal, "human_review_flag", False)),
        "relevance_score": getattr(signal, "relevance_score", None),
        "evidence_score": getattr(signal, "evidence_score", None),
        "impact_score": getattr(signal, "impact_score", None),
        "urgency_score": getattr(signal, "urgency_score", None),
        "liquidity_score": getattr(signal, "liquidity_score", None),
        "has_invalidation": bool(getattr(signal, "invalidation", None)),
        "rationale_chars": len(rationale),
        "latency_ms": round(float(latency_ms), 2),
    }
    return _filter(payload, ALLOWED_OUTPUT_FIELDS)


def trace_classification(
    item: Any,
    signal: Any,
    *,
    model: str | None,
    outcome: str,
    latency_ms: float,
    fallback_category: str | None = None,
    macro_context_lines: int = 0,
) -> None:
    """The single entry point callers use. Everything after the enablement check
    — including payload construction — runs inside this module's try/except, so
    a malformed item or signal can never break classification.

    `cfg` is not a parameter here and must never become one: the redaction
    contract is that only `item` and `signal` cross this boundary, and only the
    allowlisted fields of those are read.
    """
    if not is_enabled():
        return
    try:
        inputs = build_input_payload(item, model, macro_context_lines=macro_context_lines)
        outputs = build_output_payload(
            signal, outcome=outcome, latency_ms=latency_ms, fallback_category=fallback_category
        )
    except Exception as exc:  # noqa: BLE001 — tracing must never break the pipeline
        log.debug("langsmith_tracing: payload build failed (%s) — trace skipped", type(exc).__name__)
        return
    emit_classification(inputs, outputs)


def emit_classification(inputs: dict, outputs: dict) -> None:
    """Send one classification run. Never raises, never blocks the pipeline."""
    if not is_enabled():
        return
    try:
        record = {
            "name": RUN_NAME,
            "run_type": RUN_TYPE,
            "tags": list(BASE_TAGS),
            "inputs": _filter(inputs, ALLOWED_INPUT_FIELDS),
            "outputs": _filter(outputs, ALLOWED_OUTPUT_FIELDS),
        }
        (_sink or _langsmith_sink)(record)
    except Exception as exc:  # noqa: BLE001 — tracing must never break the pipeline
        log.debug("langsmith_tracing: emit failed (%s) — ignored", type(exc).__name__)


def _langsmith_sink(record: dict) -> None:
    """Real transport. Imported lazily so `langsmith` stays an optional dependency."""
    global _client
    if _client is None:
        from langsmith import Client  # type: ignore[import-not-found]

        _client = Client()
    end = datetime.now(timezone.utc)
    start = end - timedelta(milliseconds=float(record["outputs"].get("latency_ms", 0.0)))
    _client.create_run(
        name=record["name"],
        run_type=record["run_type"],
        inputs=record["inputs"],
        outputs=record["outputs"],
        tags=record["tags"],
        start_time=start,
        end_time=end,
    )


def _age_hours(timestamp: Any) -> float | None:
    if not isinstance(timestamp, datetime):
        return None
    ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600, 2)
