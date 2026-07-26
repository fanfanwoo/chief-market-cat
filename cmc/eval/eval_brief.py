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
