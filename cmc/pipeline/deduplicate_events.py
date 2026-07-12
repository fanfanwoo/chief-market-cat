"""Deduplicate market/news events while preserving provenance."""

from cmc.schemas.items import NormalizedMarketItem


def deduplicate_events(items: list[NormalizedMarketItem], _cfg: dict) -> list[NormalizedMarketItem]:
    seen: dict[str, NormalizedMarketItem] = {}
    for item in items:
        key = f"{item.normalized_asset}:{item.title.strip().lower()}"
        if key not in seen:
            seen[key] = item
            continue
        kept = seen[key]
        kept.duplicate_count += 1
        kept.duplicate_source_names.append(item.source_name)
        kept.duplicate_item_ids.append(item.id)
    return list(seen.values())

