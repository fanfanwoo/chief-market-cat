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
