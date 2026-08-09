"""Test-suite guarantees.

The whole suite is offline. Any outbound socket is a bug — an accidental Gemini /
NewsAPI / FRED / yfinance / LangSmith call would consume quota, hang CI, and make
"the tests pass" meaningless. Rather than trusting each test to mock correctly,
block the syscall: a test that tries to open a connection fails loudly and fast
instead of stalling on a network timeout.
"""

import socket

import pytest


class NetworkAccessAttempted(RuntimeError):
    """Raised when a test tries to open a network connection."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Block outbound connections for every test. Local sockets stay usable."""

    def _blocked(*args, **kwargs):
        # Bound methods pass self first, module functions don't — accept both.
        target = next((a for a in args if isinstance(a, (tuple, str))), args)
        raise NetworkAccessAttempted(
            f"test attempted a network connection to {target!r} — "
            "mock the external call instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked, raising=False)
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked, raising=False)
