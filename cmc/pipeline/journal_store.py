"""Decision journal stage placeholder."""

from pathlib import Path


def journal_event(event: dict, path: Path | None = None) -> dict:
    return {"status": "not_persisted", "event": event, "path": str(path) if path else None}

