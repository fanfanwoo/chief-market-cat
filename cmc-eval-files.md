# CMC Eval Files

Combined reference for all eval & tracing files in the chief-market-cat project.

---

## CMC-eval-tracing-primer.md

# Eval + Tracing, learned on CMC

A hands-on primer for going from "I've seen LangSmith trace evals" to "I can
instrument my own system and write evals against it." Everything here runs on
**CMC itself**, offline, with no API keys. Once the mental model clicks, moving
to LangSmith or Vertex is just swapping one decorator.

---

## TL;DR — the two practices

| Practice | Question it answers | In this repo |
|----------|--------------------|--------------|
| **Tracing** | *What did my code actually do?* (inputs, outputs, timing, nesting, errors) | `cmc/eval/tracing.py` |
| **Evals** | *Is the output correct, and did it get worse?* | `cmc/eval/eval_correlations.py`, `cmc/eval/eval_brief.py` |

Tracing is observation. Evals are grading. You need both: tracing tells you what
happened on one run; evals tell you whether it was *good*, across a dataset,
every time you change something.

---

## The mental model (five words)

- **Span** — one recorded step (usually one function call): its inputs, output, duration, and parent.
- **Trace** — all the spans from one top-level run, linked into a tree.
- **Dataset** — a set of cases you evaluate against (inputs, and ideally a reference/label).
- **Evaluator** — a function that scores one output. Either a deterministic check *or* an LLM-as-judge.
- **Regression gate** — re-run the evals on every change; block the change if scores drop.

That's the whole vocabulary. LangSmith, Vertex Gen AI Eval, Weave, Langfuse —
all of them are elaborations on those five words.

---

## What we built

```
cmc/eval/
  tracing.py           # @trace decorator + span() context manager → traces.jsonl
  eval_correlations.py # RUNG 1: deterministic evals (clear right/wrong)
  eval_brief.py        # RUNG 2: LLM-as-judge evals (no single right answer)
data/eval/
  traces.jsonl         # every span, one JSON per line (created on first run)
```

Run them:

```bash
python -m cmc.eval.eval_correlations   # prints a scorecard, exits non-zero on failure
python -m cmc.eval.eval_brief          # grades the judge against human labels
```

Both print a scorecard and write spans to `data/eval/traces.jsonl`.

---

## Rung 1 — deterministic evals (start here)

We start with `compute_correlations` on purpose: it's **deterministic** and we can
manufacture **ground truth**. The trick is to synthesise the *inputs* from a known
recipe, so we already know the right *output*:

> Build returns as `asset = beta × market + noise`. A positive `beta` must come
> out positively correlated, a negative `beta` inverse, and a `beta ≈ 0` asset
> independent (and therefore dropped by the `|r| ≥ 0.30` threshold).

Because we know the answer, the evaluators are plain assertions — no LLM needed:

- **properties** — must hold for *any* correlation output: `|r| ≤ 1`, no self-pairs, no duplicate pairs.
- **expected_signs** — the AAPL/MSFT pair is positive; AAPL/GLD is inverse.
- **threshold_filter** — the independent `NOISE` asset must not appear.
- **min_abs_strength** — two identical series come out at ≈ +1.0.
- **determinism** — same input twice → identical output. (Cheap, and catches a huge class of regressions.)

Instrumenting the real function is non-invasive — we *wrap* it rather than edit it:

```python
from cmc.pipeline.compute_correlations import _corr_links_from_returns
from cmc.eval.tracing import trace

traced_corr_links = trace(name="corr_links_from_returns", tags=["correlations"])(
    _corr_links_from_returns
)
```

Current result: **15/15 checks pass**. If a future change (say, a new
`min_abs_r`, or a pandas upgrade) breaks a sign or the threshold, the scorecard
goes red and the process exits non-zero — a regression gate you can drop into CI.

---

## Rung 2 — LLM-as-judge (for the brief)

The daily brief has no single right answer, so plain assertions don't fit. The
thing we care about is *faithfulness*: **does the brief only claim what the
evidence supports?** That's a judgement, so we use an LLM to make it — an
*LLM-as-judge*.

Two lessons baked into `eval_brief.py`:

1. **The judge is just another traced call with a rubric prompt.** The rubric
   (`make_judge_prompt`) literally *is* your definition of "good" — writing it
   well is most of the work. The judge returns structured output:
   `{"verdict": "faithful"|"unfaithful", "score": 0-1, "reason": "..."}`.

2. **Calibrate the judge before you trust it.** Each case ships a *human label*,
   and the run grades **judge vs. human agreement** — not the brief. Only once
   the judge reliably matches human judgement do you turn it loose on new briefs.
   This is exactly the LangSmith workflow (label a dataset → score the evaluator
   against it).

So this file runs "backwards" on purpose: it's grading the grader. It ships a
deterministic `stub_judge` (flags any number in the brief that's absent from the
evidence) so it runs offline and agrees with the human labels **3/3**. To use a
real model, pass your own `judge_fn` — the scaffold in `real_llm_judge` shows
where the Anthropic call goes; the harness around it doesn't change.

---

## Reading a trace

Each line in `data/eval/traces.jsonl` is one span. A correlation span looks like:

```json
{
  "name": "corr_links_from_returns", "tags": ["correlations"],
  "parent_id": "6b299209d4f8", "duration_ms": 0.586, "status": "ok",
  "inputs": {"args": [{"type": "DataFrame", "shape": [250, 4],
             "columns": ["AAPL","MSFT","GLD","NOISE"]}, 0.3, 200]},
  "output": {"type": "list", "len": 3,
             "head": [["AAPL","MSFT",0.37], ["AAPL","GLD",-0.34]]}
}
```

`parent_id` links spans into a tree — in the eval runs you'll see each
`eval_case` / `judge_case` span as the parent of the compute/judge span beneath
it. That tree is what LangSmith renders visually; here it's just JSON you can
`grep`.

---

## Mapping to LangSmith (and a word on Vertex)

| This harness | LangSmith |
|--------------|-----------|
| `@trace` / `span()` | `@traceable` / run tree |
| `traces.jsonl` | the trace UI |
| `dataset()` / `CASES` | a LangSmith **Dataset** |
| an evaluator function | a LangSmith **Evaluator** (code or LLM) |
| judge-vs-human agreement | evaluator calibration against a labelled dataset |
| non-zero exit on failure | CI regression gates |

You already have the concepts now, so LangSmith becomes: install the SDK, swap
`@trace` for `@traceable`, push the dataset, and read the tree in their UI
instead of a JSONL file. **Vertex AI Gen AI Evaluation** is the same idea inside
Google Cloud — reach for it only if you're deploying on GCP/Gemini; it's a much
bigger surface than you need to learn the craft.

---

## Where to take it next

1. **Wire the correlation evals into CI** — they already exit non-zero on failure.
2. **Add cases** — a real historical window with a known relationship (e.g. gold vs. equities during a risk-off week) makes a great regression fixture.
3. **Plug in a real judge** — implement `real_llm_judge`, then *expand the labelled set* and keep agreement high before trusting it.
4. **Trace the live pipeline** — drop `@trace` on `fetch_market_data`, `score_watchlist`, and `summarize_brief` to see an end-to-end run tree, then evaluate each stage.
5. **Graduate the tool** — once you're fluent, move the whole thing to LangSmith with the mapping above.

*This primer is about engineering practice, not trading. The evals check whether
CMC's outputs are internally faithful and stable — not whether any signal is a
good trade.*

---

## chief-market-cat/cmc/eval/__init__.py

```python
"""CMC evaluation & tracing harness.

A small, dependency-free teaching harness that shows the two core practices
behind LangSmith / Vertex AI Gen AI Evaluation and any LLM-observability tool:

  - tracing   → record what a function did (inputs, outputs, timing, nesting)
  - evals     → score those outputs against expectations on a dataset

Start with `eval_correlations` (deterministic, clear right/wrong answers), then
graduate to `eval_brief` (LLM-as-judge, for outputs with no single right answer).
"""
```

---

## chief-market-cat/cmc/eval/tracing.py

```python
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
```

---

## chief-market-cat/cmc/eval/eval_brief.py

```python
"""LLM-as-judge evals for the daily brief — the second rung.

The correlation module had one right answer, so we scored it with plain checks.
The **brief** doesn't: many phrasings are fine, and the thing we actually care
about — "does the brief only claim things the evidence supports?" — is a
judgement call. That's what an *LLM-as-judge* is for: an LLM reads the evidence
and the output and returns a structured verdict.

Two ideas this file teaches:

  1. The judge is just another traced call with a rubric prompt. You can swap the
     `judge_fn` for a real LLM without changing the harness.

  2. You must **calibrate the judge**: check its verdicts against a few
     human-labelled cases before you trust it. Here each case ships a human label
     and we score judge-vs-human agreement — exactly what you'd do in LangSmith.

A deterministic `stub_judge` (no network) stands in for the LLM so this runs
offline. Point `--real` at your own model by passing a judge_fn to `run()`.

Run it:
    python -m cmc.eval.eval_brief
"""
from __future__ import annotations

import re
import sys
from typing import Callable

from cmc.eval.tracing import trace, span, reset_traces, read_traces

# ── 1. DATASET: evidence + a candidate brief + a HUMAN label ─────────────────
# The label is what a careful human reviewer decided. We use it to grade the
# judge, not the brief. "unfaithful" = the brief asserts something the evidence
# does not support (a hallucinated number / claim).
CASES = [
    {
        "name": "faithful_basic",
        "evidence": [
            "VIX latest value 18.4 (trend: -0.6)",
            "US 10Y yield 4.21%",
            "S&P 500 up 1.3% on the session",
        ],
        "brief": ("Risk tone constructive: VIX at 18.4 and easing, 10Y near 4.21%. "
                  "S&P +1.3% supports a risk-on read."),
        "label": "faithful",
    },
    {
        "name": "hallucinated_number",
        "evidence": [
            "VIX latest value 18.4 (trend: -0.6)",
            "US 10Y yield 4.21%",
        ],
        "brief": ("Markets are panicking — VIX has spiked to 31 and the 10Y is at 5.8%, "
                  "a clear risk-off regime."),
        "label": "unfaithful",   # 31 and 5.8 appear nowhere in the evidence
    },
    {
        "name": "faithful_hedged",
        "evidence": [
            "Gold breakout to all-time high",
            "Real yields falling",
        ],
        "brief": ("Gold's breakout with falling real yields is constructive, but with no "
                  "confirmation yet this is monitor-only, not a fresh long."),
        "label": "faithful",
    },
]


# ── 2. THE JUDGE ─────────────────────────────────────────────────────────────
def make_judge_prompt(evidence: list[str], brief: str) -> str:
    """The rubric. In a real system this goes to an LLM. Keeping it explicit is
    half the work of good evals — the prompt IS the spec of 'good'."""
    ev = "\n".join(f"- {e}" for e in evidence)
    return (
        "You are a careful markets fact-checker. Decide whether the BRIEF makes "
        "only claims supported by the EVIDENCE. Any figure or claim not grounded "
        "in the evidence makes it unfaithful.\n\n"
        f"EVIDENCE:\n{ev}\n\nBRIEF:\n{brief}\n\n"
        "Return JSON: {\"verdict\": \"faithful\"|\"unfaithful\", "
        "\"score\": 0.0-1.0, \"reason\": \"...\"}"
    )


_NUM = re.compile(r"\d+\.?\d*")


@trace(name="judge_brief", tags=["eval", "llm-judge"])
def stub_judge(prompt: str) -> dict:
    """Deterministic stand-in for an LLM judge (so this runs offline).

    Heuristic: pull EVIDENCE and BRIEF back out of the prompt, then flag any
    number in the brief that is absent from the evidence. A real LLM judge would
    reason over meaning, not just numbers — but this mirrors the shape of the
    output (verdict + score + reason) so the harness is identical either way.
    """
    ev_block = prompt.split("EVIDENCE:")[1].split("BRIEF:")[0]
    brief_block = prompt.split("BRIEF:")[1].split("Return JSON")[0]
    ev_nums = set(_NUM.findall(ev_block))
    brief_nums = set(_NUM.findall(brief_block))
    ungrounded = sorted(brief_nums - ev_nums)
    if ungrounded:
        return {"verdict": "unfaithful", "score": 0.2,
                "reason": f"ungrounded figures: {ungrounded}"}
    return {"verdict": "faithful", "score": 0.95, "reason": "all figures grounded"}


def real_llm_judge(client) -> Callable[[str], dict]:
    """Factory for a REAL judge. Wire your model here, e.g. Anthropic:

        import json
        def judge_fn(prompt):
            msg = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return json.loads(msg.content[0].text)
        return trace(name="judge_brief", tags=["eval","llm-judge"])(judge_fn)

    Returned function must have the same {verdict, score, reason} shape.
    """
    raise NotImplementedError("Provide a client and implement per the docstring.")


# ── 3. RUNNER: grade the JUDGE against human labels (calibration) ─────────────
def run(judge_fn: Callable[[str], dict] = stub_judge) -> int:
    reset_traces()
    rows, agree, total = [], 0, 0
    for case in CASES:
        with span("judge_case", tags=["eval"], case=case["name"]):
            prompt = make_judge_prompt(case["evidence"], case["brief"])
            verdict = judge_fn(prompt)
        total += 1
        matches = verdict["verdict"] == case["label"]
        agree += matches
        rows.append((case["name"], case["label"], verdict["verdict"],
                     verdict["score"], matches, verdict["reason"]))

    print("\n  CMC · brief faithfulness (LLM-as-judge, calibration run)")
    print("  " + "-" * 78)
    print(f"  {'case':<22}{'human':<12}{'judge':<12}{'score':<7}{'agree':<7}reason")
    print("  " + "-" * 78)
    for name, label, verdict, score, matches, reason in rows:
        print(f"  {name:<22}{label:<12}{verdict:<12}{score:<7}"
              f"{('yes' if matches else 'NO'):<7}{reason}")
    print("  " + "-" * 78)
    rate = 100 * agree / total if total else 0
    print(f"  judge agrees with human on {agree}/{total} cases ({rate:.0f}%)")
    print(f"  spans recorded: {len(read_traces())}  →  data/eval/traces.jsonl")
    print("  (grade the JUDGE first; only trust it on the brief once agreement is high)\n")
    return 0 if agree == total else 1


if __name__ == "__main__":
    sys.exit(run())
```

---

## chief-market-cat/cmc/eval/eval_correlations.py

```python
"""Deterministic evals for the correlation module — the gentle first rung.

Why correlations are the ideal place to start learning evals: the module is
*deterministic* and we can build **ground truth**. We synthesise price returns
from a known recipe (a market factor plus noise), so we already know which pairs
must come out positive, which must be inverse, and which are independent and must
be dropped. That means we can write plain pass/fail checks — no LLM judge needed.

Run it:
    python -m cmc.eval.eval_correlations

It traces every call (see data/eval/traces.jsonl) and prints a scorecard. It
exits non-zero if any eval fails, so you can wire it into CI as a regression gate.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from cmc.pipeline.compute_correlations import _corr_links_from_returns
from cmc.eval.tracing import trace, span, reset_traces, read_traces

# Instrument the REAL function without editing it — this is how you add tracing
# to existing code: wrap it. Every call now records a span.
traced_corr_links = trace(name="corr_links_from_returns", tags=["correlations"])(
    _corr_links_from_returns
)

LOOKBACK = 200
MIN_ABS_R = 0.30


# ── 1. DATASET: synthetic returns with KNOWN structure ───────────────────────
def _returns(n: int, seed: int, spec: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """Build a returns frame. spec[asset] = (loading_on_market, idio_vol).
    A positive loading → moves with the market; negative → inverse; ~0 → noise."""
    rng = np.random.default_rng(seed)
    market = rng.normal(0, 0.01, n)
    cols = {}
    for asset, (beta, idio) in spec.items():
        cols[asset] = beta * market + rng.normal(0, idio, n)
    return pd.DataFrame(cols)


def dataset() -> list[dict]:
    """Each case carries its own ground truth (expectations)."""
    return [
        {
            "name": "factor_model",
            "returns": _returns(250, 42, {
                "AAPL": (0.90, 0.010),
                "MSFT": (0.85, 0.010),
                "GLD":  (-0.55, 0.011),   # inverse to the market
                "NOISE": (0.00, 0.020),   # independent — should be dropped
            }),
            "expect_signs": [("AAPL", "MSFT", "pos"), ("AAPL", "GLD", "neg"),
                             ("MSFT", "GLD", "neg")],
            "expect_absent": ["NOISE"],
        },
        {
            "name": "identical_series",
            "returns": (lambda df: df.assign(TWIN=df["A"]))(
                _returns(250, 7, {"A": (0.9, 0.01), "B": (0.2, 0.02)})
            ),
            "expect_signs": [("A", "TWIN", "pos")],   # perfectly correlated ≈ +1.0
            "expect_min_abs": {("A", "TWIN"): 0.98},
        },
        {
            "name": "independent_noise",
            "returns": _returns(250, 123, {
                "X": (0.0, 0.02), "Y": (0.0, 0.02), "Z": (0.0, 0.02),
            }),
            "expect_absent": ["X", "Y", "Z"],   # nothing should clear the threshold
        },
    ]


# ── 2. EVALUATORS: score one output against a case's ground truth ────────────
def _pair_lookup(links: list[list]) -> dict[frozenset, float]:
    return {frozenset((a, b)): r for a, b, r in links}


def evaluator_properties(case, links) -> dict:
    """Structural sanity that must hold for ANY correlation output."""
    problems = []
    for a, b, r in links:
        if a == b:
            problems.append(f"self-pair {a}")
        if not (-1.0001 <= r <= 1.0001):
            problems.append(f"|r|>1 for {a},{b}={r}")
    seen = [frozenset((a, b)) for a, b, _ in links]
    if len(seen) != len(set(seen)):
        problems.append("duplicate pair emitted")
    return {"evaluator": "properties", "passed": not problems,
            "detail": "ok" if not problems else "; ".join(problems)}


def evaluator_expected_signs(case, links) -> dict:
    lut = _pair_lookup(links)
    problems = []
    for a, b, want in case.get("expect_signs", []):
        r = lut.get(frozenset((a, b)))
        if r is None:
            problems.append(f"{a}~{b} missing")
        elif want == "pos" and r <= 0:
            problems.append(f"{a}~{b} should be +, got {r}")
        elif want == "neg" and r >= 0:
            problems.append(f"{a}~{b} should be −, got {r}")
    return {"evaluator": "expected_signs", "passed": not problems,
            "detail": "ok" if not problems else "; ".join(problems)}


def evaluator_threshold(case, links) -> dict:
    """Assets meant to be independent must be filtered out by |r| >= min_abs_r."""
    present = {x for a, b, _ in links for x in (a, b)}
    leaked = [x for x in case.get("expect_absent", []) if x in present]
    return {"evaluator": "threshold_filter", "passed": not leaked,
            "detail": "ok" if not leaked else f"weak assets leaked: {leaked}"}


def evaluator_min_abs(case, links) -> dict:
    lut = _pair_lookup(links)
    problems = []
    for (a, b), floor in case.get("expect_min_abs", {}).items():
        r = lut.get(frozenset((a, b)))
        if r is None or abs(r) < floor:
            problems.append(f"|{a}~{b}|={r} < {floor}")
    return {"evaluator": "min_abs_strength", "passed": not problems,
            "detail": "ok" if not problems else "; ".join(problems)}


def evaluator_determinism(case, links) -> dict:
    """Same inputs → identical output. A cheap, powerful regression check."""
    again = traced_corr_links(case["returns"], MIN_ABS_R, LOOKBACK)
    passed = again == links
    return {"evaluator": "determinism", "passed": passed,
            "detail": "stable" if passed else "output changed on re-run"}


EVALUATORS = [evaluator_properties, evaluator_expected_signs,
              evaluator_threshold, evaluator_min_abs, evaluator_determinism]


# ── 3. RUNNER: trace each case, score it, print a scorecard ───────────────────
def run() -> int:
    reset_traces()
    rows, n_pass, n_total = [], 0, 0
    for case in dataset():
        with span("eval_case", tags=["eval"], case=case["name"]):
            links = traced_corr_links(case["returns"], MIN_ABS_R, LOOKBACK)
            for ev in EVALUATORS:
                res = ev(case, links)
                n_total += 1
                n_pass += res["passed"]
                rows.append((case["name"], res["evaluator"], res["passed"], res["detail"]))

    # scorecard
    print("\n  CMC · correlation evals")
    print("  " + "-" * 68)
    print(f"  {'case':<18}{'evaluator':<20}{'result':<8}detail")
    print("  " + "-" * 68)
    for case_name, ev, passed, detail in rows:
        mark = "PASS" if passed else "FAIL"
        print(f"  {case_name:<18}{ev:<20}{mark:<8}{detail}")
    print("  " + "-" * 68)
    rate = 100 * n_pass / n_total if n_total else 0
    print(f"  {n_pass}/{n_total} checks passed ({rate:.0f}%)")
    print(f"  spans recorded: {len(read_traces())}  →  data/eval/traces.jsonl\n")

    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(run())
```

---

## chief-market-cat/data/eval/traces.jsonl

```jsonl
{"trace_id": "27d0c4689552", "span_id": "e1e5945d237f", "parent_id": "5e0a144f7ea5", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.988656+00:00", "duration_ms": 0.17, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 4], "columns": ["AAPL", "MSFT", "GLD", "NOISE"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 3, "head": [{"type": "list", "len": 3, "head": ["'AAPL'", "'MSFT'", 0.37]}, {"type": "list", "len": 3, "head": ["'AAPL'", "'GLD'", -0.34]}, {"type": "list", "len": 3, "head": ["'MSFT'", "'GLD'", -0.3]}]}}
{"trace_id": "27d0c4689552", "span_id": "f90f70157846", "parent_id": "5e0a144f7ea5", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.989118+00:00", "duration_ms": 0.112, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 4], "columns": ["AAPL", "MSFT", "GLD", "NOISE"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 3, "head": [{"type": "list", "len": 3, "head": ["'AAPL'", "'MSFT'", 0.37]}, {"type": "list", "len": 3, "head": ["'AAPL'", "'GLD'", -0.34]}, {"type": "list", "len": 3, "head": ["'MSFT'", "'GLD'", -0.3]}]}}
{"trace_id": "27d0c4689552", "span_id": "5e0a144f7ea5", "parent_id": null, "name": "eval_case", "tags": ["eval"], "metadata": {"case": "factor_model"}, "ts": "2026-07-26T09:35:18.989433+00:00", "duration_ms": 0.945, "status": "ok", "error": null}
{"trace_id": "2a28a372cba9", "span_id": "d7703ff6b31a", "parent_id": "16fb9a960c25", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.989983+00:00", "duration_ms": 0.155, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 3], "columns": ["A", "B", "TWIN"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 1, "head": [{"type": "list", "len": 3, "head": ["'A'", "'TWIN'", 1.0]}]}}
{"trace_id": "2a28a372cba9", "span_id": "7b678d82d50a", "parent_id": "16fb9a960c25", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.990461+00:00", "duration_ms": 0.121, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 3], "columns": ["A", "B", "TWIN"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 1, "head": [{"type": "list", "len": 3, "head": ["'A'", "'TWIN'", 1.0]}]}}
{"trace_id": "2a28a372cba9", "span_id": "16fb9a960c25", "parent_id": null, "name": "eval_case", "tags": ["eval"], "metadata": {"case": "identical_series"}, "ts": "2026-07-26T09:35:18.990799+00:00", "duration_ms": 0.973, "status": "ok", "error": null}
{"trace_id": "dc58a9efe342", "span_id": "249babd79da7", "parent_id": "4985d009859e", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.991235+00:00", "duration_ms": 0.09, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 3], "columns": ["X", "Y", "Z"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 0, "head": []}}
{"trace_id": "dc58a9efe342", "span_id": "e601af8c5f6d", "parent_id": "4985d009859e", "name": "corr_links_from_returns", "tags": ["correlations"], "ts": "2026-07-26T09:35:18.991614+00:00", "duration_ms": 0.075, "status": "ok", "error": null, "inputs": {"args": [{"type": "DataFrame", "shape": [250, 3], "columns": ["X", "Y", "Z"]}, 0.3, 200], "kwargs": {}}, "output": {"type": "list", "len": 0, "head": []}}
{"trace_id": "dc58a9efe342", "span_id": "4985d009859e", "parent_id": null, "name": "eval_case", "tags": ["eval"], "metadata": {"case": "independent_noise"}, "ts": "2026-07-26T09:35:18.991917+00:00", "duration_ms": 0.775, "status": "ok", "error": null}
```
