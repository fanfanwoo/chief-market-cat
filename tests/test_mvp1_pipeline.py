from datetime import datetime, timezone
import sys

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
    cfg = load_config()
    assert sorted(cfg.keys()) == ["pipeline", "portfolio", "risk", "secrets", "sources"]
    assert is_placeholder(cfg["secrets"].get("gemini_key"))


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

    def fake_risk(signals: list[SignalItem], _cfg: dict) -> tuple[list[SignalItem], list[SignalItem]]:
        return signals, []

    def fake_score(signals: list[SignalItem], _cfg: dict) -> list[ScoredSignal]:
        return [ScoredSignal(**vars(signals[0]), watchlist_score=0.82, rank=1)]

    def fake_journal(event: dict, path=None) -> dict:
        captured_journal_events.append(event)
        return {"status": "captured", "path": path}

    monkeypatch.setattr("cmc.run.fetch_market_data_stage.fetch_market_data", lambda _cfg: [raw])
    monkeypatch.setattr("cmc.run.fetch_news_macro_stage.fetch_news_macro", lambda _cfg: [])
    monkeypatch.setattr("cmc.run.classify_signal_stage.classify_signals", fake_classify)
    monkeypatch.setattr("cmc.run.verify_signal_stage.verify_signals", fake_verify)
    monkeypatch.setattr("cmc.run.risk_gate_stage.apply_risk_gate", fake_risk)
    monkeypatch.setattr("cmc.run.score_watchlist_stage.score_watchlist", fake_score)
    monkeypatch.setattr("cmc.run.summarize_brief_stage.summarize_brief", lambda *_args: "brief")
    monkeypatch.setattr("cmc.run.alert_human_stage.alert_human", lambda brief, _cfg: {"status": "not_sent", "brief_chars": len(brief)})
    monkeypatch.setattr("cmc.run.journal_store_stage.journal_event", fake_journal)

    sys.modules.pop("cmc.pipeline.paper_trade", None)
    result = run_pipeline()

    assert result["status"] == "mvp1_completed"
    assert result["counts"]["market_items"] == 1
    assert result["counts"]["classified_signals"] == 1
    assert result["counts"]["scored_signals"] == 1
    assert result["brief_chars"] == len("brief")
    assert result["alert"]["status"] == "not_sent"
    assert captured_journal_events[0]["event_type"] == "mvp1_run_summary"
    assert "cmc.pipeline.paper_trade" not in sys.modules
