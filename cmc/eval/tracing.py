"""Minimal tracing — the same idea LangSmith / OpenTelemetry implement.

A *trace* is a record of one execution. A *span* is one step inside it (usually
one function call), capturing its inputs, output, duration, and where it sits in
the call tree. Collect spans and you can answer: what ran, what did it return,
how long did it take, and what failed.

This module gives you a `@trace` decorator and a `span(...)` context manager that
write spans to `data/eval/traces.jsonl` (one JSON object per line). It is
deliberately tiny and has no dependencies so you can read the whole thing.

── How this maps to LangSmith ──────────────────────────────────────────────
    this module            LangSmith
    -------------          --------------------------------
    @trace                 @traceable
    span_id / parent_id     run tree (parent/child runs)
    traces.jsonl            the LangSmith trace UI
    tags=[...]              run tags / metadata
    status / error          run status, error surfacing
When you move to LangSmith you keep the *mental model* and swap the decorator.
"""
from __future__ import annotations

import functools
import json
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "traces.jsonl"

# Tracks the currently-open span so nested calls record their parent.
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)
# Groups spans belonging to one top-level run (one "trace").
_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)


def _summarize(obj: Any, limit: int = 240) -> Any:
    """Turn an argument or return value into something small + JSON-safe.
    Big objects (DataFrames, long lists) become a shape/length summary."""
    # pandas DataFrame / Series without importing pandas
    cls = type(obj).__name__
    if cls in ("DataFrame", "Series"):
        shape = getattr(obj, "shape", None)
        cols = list(getattr(obj, "columns", []))[:8]
        return {"type": cls, "shape": list(shape) if shape else None, "columns": cols}
    if isinstance(obj, (list, tuple)):
        head = [_summarize(x, 80) for x in list(obj)[:5]]
        return {"type": cls, "len": len(obj), "head": head}
    if isinstance(obj, dict):
        return {"type": "dict", "keys": list(obj)[:10]}
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    s = repr(obj)
    return s if len(s) <= limit else s[:limit] + "…"


def _record(span: dict) -> None:
    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(span) + "\n")
    except OSError:
        pass  # tracing must never break the thing it's observing


def trace(name: str | None = None, tags: list[str] | None = None,
          capture_io: bool = True):
    """Decorator: record a span every time the wrapped function runs.

    Example:
        @trace(name="corr_links", tags=["correlations"])
        def build_links(returns): ...
    """
    def decorator(fn):
        span_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            span_id = uuid.uuid4().hex[:12]
            parent_id = _current_span.get()
            trace_id = _current_trace.get() or uuid.uuid4().hex[:12]
            tr_token = _current_trace.set(trace_id)
            sp_token = _current_span.set(span_id)
            start = time.perf_counter()
            status, error, output = "ok", None, None
            try:
                output = fn(*args, **kwargs)
                return output
            except Exception as e:  # noqa: BLE001 — we re-raise
                status, error = "error", repr(e)
                raise
            finally:
                span = {
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_id": parent_id,
                    "name": span_name,
                    "tags": tags or [],
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    "status": status,
                    "error": error,
                }
                if capture_io:
                    span["inputs"] = {
                        "args": [_summarize(a) for a in args],
                        "kwargs": {k: _summarize(v) for k, v in kwargs.items()},
                    }
                    span["output"] = _summarize(output)
                _record(span)
                _current_span.reset(sp_token)
                _current_trace.reset(tr_token)

        return wrapper

    return decorator


@contextmanager
def span(name: str, tags: list[str] | None = None, **metadata):
    """Context manager for a manual span around a block of code.

    Example:
        with span("score_case", tags=["eval"], case="gld_inverse"):
            ...
    """
    span_id = uuid.uuid4().hex[:12]
    parent_id = _current_span.get()
    trace_id = _current_trace.get() or uuid.uuid4().hex[:12]
    tr_token = _current_trace.set(trace_id)
    sp_token = _current_span.set(span_id)
    start = time.perf_counter()
    status, error = "ok", None
    try:
        yield
    except Exception as e:  # noqa: BLE001
        status, error = "error", repr(e)
        raise
    finally:
        _record({
            "trace_id": trace_id, "span_id": span_id, "parent_id": parent_id,
            "name": name, "tags": tags or [], "metadata": metadata,
            "ts": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((time.perf_counter() - start) * 1000, 3),
            "status": status, "error": error,
        })
        _current_span.reset(sp_token)
        _current_trace.reset(tr_token)


def reset_traces() -> None:
    """Empty the trace log (handy at the start of an eval run). Truncates rather
    than deletes so it works even where unlink is restricted."""
    try:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRACE_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass


def read_traces() -> list[dict]:
    """Load all recorded spans (for inspection or assertions in tests)."""
    if not TRACE_PATH.exists():
        return []
    out = []
    for line in TRACE_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out
