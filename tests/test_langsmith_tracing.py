"""LangSmith tracing tests — all offline.

Design rules:
- No network, no Gemini call, no `langsmith` import (it is an optional dep).
- The capturing sink stands in for the LangSmith transport, so every assertion
  is about the exact bytes that would have been transmitted.
- Sensitive values are planted in cfg / item text, then asserted absent from the
  serialized payloads.
"""

import json
import logging
from datetime import datetime, timezone

import pytest

from cmc.eval import langsmith_tracing as ls
from cmc.pipeline import classify_signal
from cmc.pipeline.classify_signal import (
    _classify_item_traced,
    classify_signals,
)
from cmc.schemas.items import NormalizedMarketItem

# Values that must never appear in anything sent to LangSmith.
SECRET_VALUES = [
    "AIzaSyREALGEMINIKEY123",
    "abcd efgh ijkl mnop",          # gmail app password
    "trader@example.com",
    "PKREALALPACAKEY",
    "alpaca-secret-987",
]

SENSITIVE_CFG = {
    "secrets": {
        "gemini_key": SECRET_VALUES[0],
        "gmail_app_password": SECRET_VALUES[1],
        "gmail_sender": SECRET_VALUES[2],
        "gmail_recipient": SECRET_VALUES[2],
        "alpaca_key": SECRET_VALUES[3],
        "alpaca_secret": SECRET_VALUES[4],
        "newsapi_key": "newsapi-real",
        "fred_key": "fred-real",
    },
    "pipeline": {"classification": {"model": "gemini-3.1-flash-lite", "needs_review_threshold": 0.6}},
}


def _item(asset: str = "AAPL") -> NormalizedMarketItem:
    return NormalizedMarketItem(
        id="deadbeefcafe1234",
        asset=asset,
        market="US",
        title=f"{asset} rallies — contact {SECRET_VALUES[2]}",
        body=f"Body text mentioning key {SECRET_VALUES[0]} and more prose." * 3,
        source_name="test-source",
        source_type="price",
        trust_tier="market_data",
        timestamp=datetime.now(timezone.utc),
        raw_metadata={"price": 100.0, "change_1d_pct": 1.2, "api_key": SECRET_VALUES[0]},
        evidence_level="price_feed",
        evidence_category="market_data",
    )


class _StubModel:
    """Stands in for genai.GenerativeModel — no network, no quota."""

    def __init__(self, payload: dict | None = None, raise_exc: Exception | None = None):
        self._payload = payload or {
            "signal_type": "trend_continuation",
            "direction": "BULLISH",
            "confidence": 0.82,
            "rationale": f"Price up; secret {SECRET_VALUES[0]} leaked into rationale.",
            "invalidation": "Close below 95",
        }
        self._raise = raise_exc
        self.calls = 0

    def generate_content(self, _prompt):
        self.calls += 1
        if self._raise:
            raise self._raise
        return type("Resp", (), {"text": json.dumps(self._payload)})()


@pytest.fixture
def captured(monkeypatch):
    """Enable tracing and capture what the transport would have sent."""
    monkeypatch.setenv(ls.ENABLE_ENV, "1")
    monkeypatch.setenv(ls.API_KEY_ENV, "lsv2_pt_fake_key_for_tests")
    records: list[dict] = []
    ls.set_sink(records.append)
    yield records
    ls.set_sink(None)


def _blob(records: list[dict]) -> str:
    return json.dumps(records, default=str)


# ── Enablement ──────────────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv(ls.ENABLE_ENV, raising=False)
    monkeypatch.setenv(ls.API_KEY_ENV, "lsv2_pt_fake")
    assert ls.is_enabled() is False


def test_requires_api_key(monkeypatch):
    monkeypatch.setenv(ls.ENABLE_ENV, "1")
    monkeypatch.delenv(ls.API_KEY_ENV, raising=False)
    assert ls.is_enabled() is False


def test_nothing_emitted_when_disabled(monkeypatch):
    """No emission from any entry point when the flag is off.

    Uses the stub model and the placeholder-key fallback: SENSITIVE_CFG's
    gemini_key is deliberately real-looking, so it must never reach
    classify_signals, which would attempt a live Gemini call.
    """
    monkeypatch.delenv(ls.ENABLE_ENV, raising=False)
    records: list[dict] = []
    ls.set_sink(records.append)
    try:
        _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
        classify_signals([_item()], {**SENSITIVE_CFG, "secrets": {"gemini_key": "YOUR_GEMINI_KEY"}})
        ls.trace_classification(_item(), classify_signal._neutral_signal(_item(), "x"),
                                model="gemini-3.1-flash-lite", outcome="fallback", latency_ms=1.0)
        ls.emit_classification({"asset": "AAPL"}, {"outcome": "classified"})
    finally:
        ls.set_sink(None)
    assert records == []


def test_no_test_reaches_the_network(monkeypatch):
    """conftest blocks outbound sockets — proves the guard is armed."""
    import socket

    from conftest import NetworkAccessAttempted

    with pytest.raises(NetworkAccessAttempted):
        socket.create_connection(("api.smith.langchain.com", 443))


# ── Redaction ───────────────────────────────────────────────────────────────

def test_input_payload_is_allowlisted_only():
    payload = ls.build_input_payload(_item(), "gemini-3.1-flash-lite", macro_context_lines=2)
    assert set(payload) <= ls.ALLOWED_INPUT_FIELDS
    for banned in ("title", "body", "raw_metadata", "secrets", "cfg", "source_name", "api_key"):
        assert banned not in payload
    # Text becomes lengths, never content.
    assert payload["title_chars"] > 0 and payload["body_chars"] > 0
    assert payload["asset"] == "AAPL"
    assert payload["has_price_data"] is True


def test_output_payload_is_allowlisted_only():
    signal = classify_signal._neutral_signal(_item(), reason="gemini_key_not_configured")
    payload = ls.build_output_payload(signal, outcome="fallback", latency_ms=12.3,
                                      fallback_category="gemini_key_not_configured")
    assert set(payload) <= ls.ALLOWED_OUTPUT_FIELDS
    assert "rationale" not in payload and "invalidation" not in payload
    assert payload["rationale_chars"] > 0


def test_unknown_keys_are_dropped_at_the_boundary(captured):
    ls.emit_classification(
        {"asset": "AAPL", "gemini_key": SECRET_VALUES[0], "cfg": SENSITIVE_CFG},
        {"outcome": "classified", "gmail_sender": SECRET_VALUES[2], "rationale": "text"},
    )
    assert len(captured) == 1
    assert set(captured[0]["inputs"]) == {"asset"}
    assert set(captured[0]["outputs"]) == {"outcome"}
    for secret in SECRET_VALUES:
        assert secret not in _blob(captured)


def test_no_secrets_in_traced_classification(captured):
    _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    blob = _blob(captured)
    for secret in SECRET_VALUES:
        assert secret not in blob
    for key_name in ("gemini_key", "gmail_app_password", "alpaca_secret", "newsapi_key", "fred_key"):
        assert key_name not in blob
    assert "AIzaSy" not in blob


def test_no_secrets_in_fallback_path(captured):
    classify_signals([_item(), _item("MSFT")], {**SENSITIVE_CFG,
                                                "secrets": {"gemini_key": "YOUR_GEMINI_KEY"}})
    assert len(captured) == 2
    assert {r["outputs"]["fallback_category"] for r in captured} == {"gemini_key_not_configured"}
    assert "YOUR_GEMINI_KEY" not in _blob(captured)


def test_error_category_never_leaks_message(captured):
    exc = RuntimeError(f"429 quota exceeded for key={SECRET_VALUES[0]} at https://host/v1?key=x")
    assert ls.error_category(exc) == "rate_limit"
    _classify_item_traced(_StubModel(raise_exc=exc), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    blob = _blob(captured)
    assert captured[0]["outputs"]["fallback_category"] == "rate_limit"
    assert captured[0]["outputs"]["outcome"] == "error"
    assert SECRET_VALUES[0] not in blob and "https://" not in blob and "quota exceeded" not in blob


def test_string_values_are_length_capped(captured):
    ls.emit_classification({"asset": "A" * 500}, {"outcome": "classified"})
    assert len(captured[0]["inputs"]["asset"]) == ls.MAX_STR_CHARS


def test_payload_is_json_serializable_primitives(captured):
    _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    for section in ("inputs", "outputs"):
        for value in captured[0][section].values():
            assert value is None or isinstance(value, (str, int, float, bool))


# ── Behaviour is unchanged by tracing ───────────────────────────────────────

def test_tracing_does_not_change_classifier_output(monkeypatch):
    monkeypatch.delenv(ls.ENABLE_ENV, raising=False)
    off = _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")

    monkeypatch.setenv(ls.ENABLE_ENV, "1")
    monkeypatch.setenv(ls.API_KEY_ENV, "lsv2_pt_fake_key_for_tests")
    records: list[dict] = []
    ls.set_sink(records.append)
    try:
        on = _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    finally:
        ls.set_sink(None)

    assert len(records) == 1
    for field in ("signal_type", "direction", "confidence", "rationale", "invalidation",
                  "relevance_score", "evidence_score", "impact_score", "liquidity_score",
                  "human_review_flag", "human_review_reason"):
        assert getattr(off, field) == getattr(on, field)


def test_fallback_output_unchanged_by_tracing(monkeypatch):
    cfg = {**SENSITIVE_CFG, "secrets": {"gemini_key": "YOUR_GEMINI_KEY"}}
    item = _item()   # same instance both runs — timestamps are wall-clock
    monkeypatch.delenv(ls.ENABLE_ENV, raising=False)
    off = classify_signals([item], cfg)[0]

    monkeypatch.setenv(ls.ENABLE_ENV, "1")
    monkeypatch.setenv(ls.API_KEY_ENV, "lsv2_pt_fake_key_for_tests")
    ls.set_sink(lambda _record: None)
    try:
        on = classify_signals([item], cfg)[0]
    finally:
        ls.set_sink(None)

    assert vars(off) == vars(on)


def test_payload_build_failure_does_not_break_classification(captured, monkeypatch):
    """Payload construction lives inside the boundary's try/except."""
    def exploding_builder(*_args, **_kwargs):
        raise ValueError("malformed item")

    monkeypatch.setattr(ls, "build_input_payload", exploding_builder)
    signal = _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    assert signal.signal_type == "trend_continuation"
    assert signal.confidence == pytest.approx(0.82)
    assert captured == []


def test_hostile_item_does_not_break_the_boundary(captured):
    """An item whose attribute access raises must not propagate out of tracing."""
    class HostileItem:
        id = "x"

        def __getattr__(self, name):
            raise RuntimeError(f"attribute {name} blew up")

    signal = classify_signal._neutral_signal(_item(), reason="gemini_key_not_configured")
    ls.trace_classification(HostileItem(), signal, model="m", outcome="fallback", latency_ms=1.0)
    assert captured == []


def test_error_category_survives_pathological_exception():
    class Nasty(Exception):
        def __str__(self):
            raise RuntimeError("cannot stringify")

    assert ls.error_category(Nasty()) == "unknown_error"


def test_fallback_path_traces_are_fail_open(captured, monkeypatch):
    """A broken builder must not stop classify_signals returning fallbacks."""
    monkeypatch.setattr(ls, "build_output_payload", lambda *_a, **_k: 1 / 0)
    signals = classify_signals([_item()], {**SENSITIVE_CFG, "secrets": {"gemini_key": "YOUR_GEMINI_KEY"}})
    assert len(signals) == 1 and signals[0].signal_type == "no_trade_unclear"
    assert captured == []


def test_sink_failure_does_not_break_classification(captured):
    def exploding_sink(_record):
        raise RuntimeError("langsmith is down")

    ls.set_sink(exploding_sink)
    signal = _classify_item_traced(_StubModel(), _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    assert signal.signal_type == "trend_continuation"
    assert signal.confidence == pytest.approx(0.82)


def test_first_export_failure_is_warned_once(captured, caplog):
    """Fail-open must not mean fail-silent — a rejected key has to be visible."""
    class FakeResponse:
        status_code = 403

    def rejecting_sink(_record):
        exc = RuntimeError("Forbidden")
        exc.response = FakeResponse()
        raise exc

    ls.reset_failure_state()
    ls.set_sink(rejecting_sink)
    with caplog.at_level(logging.WARNING, logger="cmc.eval.langsmith_tracing"):
        for _ in range(5):
            ls.emit_classification({"asset": "AAPL"}, {"outcome": "classified"})

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "one warning per run, not one per item"
    assert "HTTP 403" in warnings[0].getMessage()
    assert ls.export_failure_count() == 5


def test_failure_warning_leaks_nothing(captured, caplog):
    """The warning names the exception type and status, never the response body."""
    class FakeResponse:
        status_code = 403
        text = f"denied for key {SECRET_VALUES[0]}"

    def rejecting_sink(_record):
        exc = RuntimeError(f"403 for https://api.smith.langchain.com?key={SECRET_VALUES[0]}")
        exc.response = FakeResponse()
        raise exc

    ls.reset_failure_state()
    ls.set_sink(rejecting_sink)
    with caplog.at_level(logging.DEBUG, logger="cmc.eval.langsmith_tracing"):
        ls.emit_classification({"asset": "AAPL"}, {"outcome": "classified"})

    blob = " ".join(r.getMessage() for r in caplog.records)
    assert SECRET_VALUES[0] not in blob
    assert "https://" not in blob


def test_classify_signals_reports_trace_health(monkeypatch, caplog):
    """The daily log states whether tracing ran and how many exports failed."""
    monkeypatch.setenv(ls.ENABLE_ENV, "1")
    monkeypatch.setenv(ls.API_KEY_ENV, "lsv2_pt_fake_key_for_tests")
    ls.set_sink(lambda _record: (_ for _ in ()).throw(RuntimeError("down")))
    try:
        with caplog.at_level(logging.INFO, logger="cmc.pipeline.classify_signal"):
            classify_signals([_item()], {**SENSITIVE_CFG, "secrets": {"gemini_key": "YOUR_GEMINI_KEY"}})
    finally:
        ls.set_sink(None)

    messages = [r.getMessage() for r in caplog.records]
    assert any("langsmith tracing enabled" in m for m in messages)
    assert ls.export_failure_count() == 1


def test_flush_is_safe_without_a_client():
    ls.reset_failure_state()
    ls.flush()   # no client constructed — must be a silent no-op
    assert ls.export_failure_count() == 0


def test_gemini_is_not_called_more_than_once_per_item(captured):
    model = _StubModel()
    _classify_item_traced(model, _item(), "", SENSITIVE_CFG, 0, "gemini-3.1-flash-lite")
    assert model.calls == 1
