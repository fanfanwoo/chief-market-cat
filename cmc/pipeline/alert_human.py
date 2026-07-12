"""Human alert delivery placeholder."""


def alert_human(brief: str, _cfg: dict) -> dict:
    return {"status": "not_sent", "brief_chars": len(brief)}

