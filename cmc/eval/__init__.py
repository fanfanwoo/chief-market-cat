"""CMC evaluation & tracing harness.

A small, dependency-free teaching harness that shows the two core practices
behind LangSmith / Vertex AI Gen AI Evaluation and any LLM-observability tool:

  - tracing   → record what a function did (inputs, outputs, timing, nesting)
  - evals     → score those outputs against expectations on a dataset

Start with `eval_correlations` (deterministic, clear right/wrong answers), then
graduate to `eval_brief` (LLM-as-judge, for outputs with no single right answer).
"""
