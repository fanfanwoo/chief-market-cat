"""JSONL storage helpers."""

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Iterable


def append_jsonl(path: Path, records: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            payload = asdict(record) if is_dataclass(record) else record
            handle.write(json.dumps(payload, default=str) + "\n")

