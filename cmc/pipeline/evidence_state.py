"""Label evidence quality before any signal classification."""

from cmc.schemas.items import NormalizedMarketItem


_CATEGORY_BY_TRUST_TIER = {
    "official": "official",
    "primary": "publisher",
    "major_publisher": "publisher",
    "market_data": "market_data",
    "aggregator": "aggregator",
    "social": "aggregator",
}


def label_evidence(items: list[NormalizedMarketItem]) -> list[NormalizedMarketItem]:
    for item in items:
        item.evidence_category = _CATEGORY_BY_TRUST_TIER.get(item.trust_tier, "aggregator")
        if item.trust_tier in {"official", "market_data"}:
            item.evidence_level = "full_body"
            item.evidence_source = item.source_type
            item.enrichment_status = "success"
            item.enrichment_reason = "trusted_source"
        elif item.body and len(item.body) >= 600:
            item.evidence_level = "full_body"
            item.evidence_source = item.source_type
            item.enrichment_status = "success"
            item.enrichment_reason = "body_present"
        elif item.body:
            item.evidence_level = "excerpt"
            item.evidence_source = item.source_type
            item.enrichment_status = "success"
            item.enrichment_reason = "excerpt_present"
        else:
            item.evidence_level = "headline_only"
            item.evidence_source = item.source_type
            item.enrichment_status = "skipped"
            item.enrichment_reason = "no_body"
    return items

