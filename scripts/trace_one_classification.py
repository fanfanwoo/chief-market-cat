#!/usr/bin/env python3
"""Generate exactly ONE classifier trace, under full control.

Modes (default is the safest):

  python3 scripts/trace_one_classification.py
      Stub model, printing sink. No Gemini call, no network, nothing sent to
      LangSmith. Prints the exact JSON payload that WOULD be transmitted.

  python3 scripts/trace_one_classification.py --send
      Stub model, real LangSmith sink. One run appears in LangSmith. Still zero
      Gemini quota. Requires: CMC_LANGSMITH_TRACING=1, LANGSMITH_API_KEY=...

  python3 scripts/trace_one_classification.py --send --live-gemini
      One real Gemini request for one item (consumes one unit of quota) and one
      LangSmith run. Requires a real gemini_key in config/secrets.yaml.

Nothing here touches email, paper trades, the dashboard, or the run journal.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cmc.eval import langsmith_tracing as ls          # noqa: E402
from cmc.pipeline.classify_signal import (            # noqa: E402
    GEMINI_MODEL,
    _classify_item_traced,
)
from cmc.schemas.items import NormalizedMarketItem    # noqa: E402

SAMPLE_JSON = json.dumps({
    "signal_type": "trend_continuation",
    "direction": "BULLISH",
    "confidence": 0.72,
    "rationale": "Stubbed classifier response for a controlled trace.",
    "invalidation": "Close below the 20-day moving average.",
})


class StubModel:
    """Returns a fixed classifier response — no network, no quota."""

    def generate_content(self, _prompt):
        return type("Resp", (), {"text": SAMPLE_JSON})()


def sample_item() -> NormalizedMarketItem:
    return NormalizedMarketItem(
        id=NormalizedMarketItem.generate_id("trace-demo"),
        asset="SPY",
        market="US",
        title="SPY extends gains as breadth improves",
        body="Synthetic body used only to exercise the classifier path.",
        source_name="trace-demo",
        source_type="price",
        trust_tier="market_data",
        timestamp=datetime.now(timezone.utc),
        raw_metadata={"price": 512.34, "change_1d_pct": 0.8, "change_5d_pct": 2.1},
        evidence_level="price_feed",
        evidence_category="market_data",
    )


def check_credentials() -> bool:
    """Read-only auth probe. Creates nothing; catches a rejected key up front.

    Worth doing because trace export is fail-open by design: a 403 produces a
    clean pipeline log and zero traces, which looks identical to tracing being
    switched off.
    """
    import os

    import requests

    url = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    try:
        resp = requests.get(
            f"{url}/api/v1/sessions",
            headers={"x-api-key": os.environ["LANGSMITH_API_KEY"]},
            params={"limit": 1},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"cannot reach LangSmith: {type(exc).__name__}")
        return False
    if resp.status_code == 200:
        print(f"credentials OK ({url})")
        return True
    print(
        f"LangSmith rejected the key: HTTP {resp.status_code}. "
        "Generate a new one at smith.langchain.com → Settings → API Keys, "
        "then update config/langsmith.env."
    )
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--send", action="store_true", help="use the real LangSmith sink")
    ap.add_argument("--live-gemini", action="store_true", help="make one real Gemini call (uses quota)")
    args = ap.parse_args()

    if not ls.is_enabled():
        print(f"tracing is OFF — set {ls.ENABLE_ENV}=1 and {ls.API_KEY_ENV}=... to emit")
        return 1

    if not check_credentials():
        return 2

    if not args.send:
        ls.set_sink(lambda record: print(json.dumps(record, indent=2, default=str)))
        print("dry run — payload below is printed locally, NOT sent to LangSmith\n")

    if args.live_gemini:
        from cmc.config import load_config

        cfg = load_config()
        import google.generativeai as genai  # type: ignore[import]

        genai.configure(api_key=cfg["secrets"]["gemini_key"])
        model_name = cfg.get("pipeline", {}).get("classification", {}).get("model", GEMINI_MODEL)
        model = genai.GenerativeModel(model_name)
    else:
        cfg = {"pipeline": {"classification": {"needs_review_threshold": 0.6}}}
        model_name, model = GEMINI_MODEL, StubModel()

    signal = _classify_item_traced(model, sample_item(), "", cfg, 0, model_name)
    print(f"\nlocal result: {signal.asset} → {signal.direction} {signal.signal_type} "
          f"(conf={signal.confidence:.2f}, review={signal.human_review_flag})")
    if args.send:
        print("one run sent to LangSmith (project = LANGSMITH_PROJECT or 'default')")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
