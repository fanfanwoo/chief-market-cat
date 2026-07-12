"""Configuration loading helpers."""

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"

PLACEHOLDER_PREFIX = "YOUR_"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data


def load_secrets() -> dict[str, Any]:
    """Load secrets.yaml, returning an empty dict if the file doesn't exist."""
    secrets_path = CONFIG_DIR / "secrets.yaml"
    if not secrets_path.exists():
        return {}
    return load_yaml(secrets_path)


def is_placeholder(value: str | None) -> bool:
    """Return True if the value is a placeholder that hasn't been filled in."""
    if not value:
        return True
    return str(value).startswith(PLACEHOLDER_PREFIX)


def load_config() -> dict[str, Any]:
    secrets = load_secrets()
    return {
        "sources": load_yaml(CONFIG_DIR / "sources.yaml"),
        "pipeline": load_yaml(CONFIG_DIR / "pipeline.yaml"),
        "risk": load_yaml(CONFIG_DIR / "risk.yaml"),
        "portfolio": load_yaml(CONFIG_DIR / "portfolio.yaml"),
        "secrets": secrets,
    }
