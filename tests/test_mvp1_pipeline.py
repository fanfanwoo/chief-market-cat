"""MVP1 pipeline smoke tests.

Design rules:
- Never assert on the *value* of a real secret (user may fill real keys).
- Monkeypatch every external call in the integration test so it runs
  offline without Gemini / NewsAPI / FRED / Gmail / yfinance.
- Key names / structure assertions stay — that's the contract we own.
"""

from datetime import datetime, timezone
from pathlib import Path

from cmc.config import is_placeholder, load_config
from cmc.pipeline.fetch_market_data import fetch_market_data
from cmc.pipeline.fetch_news_macro import fetch_news_macro
from cmc.run import run_pipeline
from cmc.schemas.items import RawMarketItem
from cmc.schemas.signals import ScoredSignal, SignalItem


def _raw_item(asset: str = "AAPL") -> RawMarketItem:
    return RawMarketItem(
        id=f"test-{asset}",
        asset=asset,
        market="US",
        title=f"{asset} test item",
        body="A deterministic test item with enough body for pipeline tests.",
        source_name="test",
        source_type="price",
        trust_tier="market_data",
        timestamp=datetime.now(timezone.utc),
        raw_metadata={"price": 100.0, "change_1d_pct": 1.0},
    )


def test_config_loads_with_secrets():
    """Config loads all five top-level keys; secrets section exists and has expected keys."""
    cfg = load_config()
    assert sorted(cfg.keys()) == ["pipeline", "portfolio", "risk", "secrets", "sources"]

    secrets = cfg["secrets"]
    # Secrets section must have these keys whether or not they are filled
    for key in ("gemini_key", "newsapi_key", "fred_key", "gmail_app_password"):
        assert key in secrets, f"Expected '{key}' in secrets"

    # is_placeholder() must return True for sentinel strings and False for real values
    assert is_placeholder("YOUR_ANYTHING_HERE") is True
    assert is_placeholder("") is True
    assert is_placeholder(None) is True
    assert is_placeholder("sk-real-key-123") is False


def test_fetch_market_data_wrapper_delegates(monkeypatch):
    expected = [_raw_item()]

    def fake_fetch(cfg: dict) -> list[RawMarketItem]:
        assert cfg == {"sources": {}}
        return expected

    monkeypatch.setattr(
        "cmc.connectors.market_data_connector.fetch_market_data",
        fake_fetch,
    )

    assert fetch_market_data({"sources": {}}) == expected


def test_fetch_news_macro_wrapper_delegates(monkeypatch):
    expected = [_raw_item("MARKET")]

    def fake_fetch(cfg: dict) -> list[RawMarketItem]:
        assert cfg == {"secrets": {}}
        return expected

    monkeypatch.setattr("cmc.connectors.news_connector.fetch_news", fake_fetch)

    assert fetch_news_macro({"secrets": {}}) == expected


def test_run_pipeline_wires_mvp1_flow(monkeypatch):
    """Full pipeline wiring test — every external call mocked, checks summary schema."""
    raw = _raw_item()
    captured_journal_events: list[dict] = []

    def fake_classify(items: list, _cfg: dict) -> list[SignalItem]:
        assert len(items) == 1
        return [
            SignalItem(
                **vars(items[0]),
                signal_type="trend_continuation",
                direction="bullish",
                confidence=0.9,
                invalidation="Close below 95",
                relevance_score=0.8,
                evidence_score=0.8,
                impact_score=0.7,
                urgency_score=0.5,
                liquidity_score=0.8,
            )
        ]

    def fake_verify(signals: list[SignalItem], **_kwargs) -> tuple[list[SignalItem], list[SignalItem]]:
        return signals, []

    def fake_risk(signals: list[SignalItem], _cfg: dict, **_kwargs) -> tuple[list[SignalItem], list[SignalItem]]:
        return signals, []

    def fake_score(signals: list[SignalItem], _cfg: dict) -> list[ScoredSignal]:
        return [ScoredSignal(**vars(signals[0]), watchlist_score=0.82, rank=1)]

    def fake_journal(event: dict, path=None) -> dict:
        captured_journal_events.append(event)
        return {"status": "captured", "path": path}

    monkeypatch.setattr("cmc.run.fetch_market_data_stage.fetch_market_data", lambda _cfg: [raw])
    monkeypatch.setattr("cmc.run.compute_correlations_stage.compute_and_cache", lambda *_: None)
    monkeypatch.setattr("cmc.run.fetch_news_macro_stage.fetch_news_macro", lambda _cfg: [])
    monkeypatch.setattr("cmc.run.classify_signal_stage.classify_signals", fake_classify)
    monkeypatch.setattr("cmc.run.verify_signal_stage.verify_signals", fake_verify)
    monkeypatch.setattr("cmc.run.risk_gate_stage.apply_risk_gate", fake_risk)
    monkeypatch.setattr("cmc.run.score_watchlist_stage.score_watchlist", fake_score)
    monkeypatch.setattr("cmc.run.summarize_brief_stage.summarize_brief", lambda *_: "brief")
    monkeypatch.setattr("cmc.run.alert_human_stage.alert_human", lambda brief, _cfg: {"status": "not_sent", "brief_chars": len(brief)})
    monkeypatch.setattr("cmc.run.paper_trade_stage.log_paper_trades", lambda *_: [])
    monkeypatch.setattr("cmc.run.generate_dashboard_stage.generate_dashboard", lambda *_: Path("data/dashboard/dashboard_test.html"))
    monkeypatch.setattr("cmc.run.journal_store_stage.journal_event", fake_journal)

    result = run_pipeline()

    # Status and top-level shape
    assert result["status"] == "completed"
    assert "run_completed_at" in result
    assert "brief_chars" in result
    assert "alert" in result

    # Counts that matter
    counts = result["counts"]
    assert counts["market_items"] == 1
    assert counts["news_macro_items"] == 0
    assert counts["classified"] == 1
    assert counts["passed_verify"] == 1
    assert counts["held_for_review"] == 0
    assert counts["risk_approved"] == 1
    assert counts["risk_blocked"] == 0
    assert counts["scored"] == 1
    assert counts["paper_trades_logged"] == 0

    # Brief and alert
    assert result["brief_chars"] == len("brief")
    assert result["alert"]["status"] == "not_sent"

    # Journal event wired correctly
    assert len(captured_journal_events) == 1
    assert captured_journal_events[0]["event_type"] == "pipeline_run"
    assert "summary" in captured_journal_events[0]
