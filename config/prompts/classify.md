You classify a single news item for a defence brief. Return STRICT JSON only:
{"kpmg_tags": [...], "domain_tags": [...], "impact_score": 1-5,
 "kpmg_sentiment": -2..2, "primary_section": "policy|market|tech"}

- kpmg_tags MUST be chosen only from: {{KPMG_TAGS}}
- domain_tags MUST be chosen only from: {{DOMAIN_TAGS}}
- impact_score: impact on the Australian defence operating environment / sector (1 low, 5 high).
- kpmg_sentiment: opportunity (positive) vs risk (negative) for KPMG and its clients.
- primary_section: the single best-fit body subsection (MECE).

Item:
{{ITEM}}
