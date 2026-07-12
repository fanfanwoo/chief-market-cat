"""Text normalization helpers."""


def compact_whitespace(value: str) -> str:
    return " ".join(value.split())

