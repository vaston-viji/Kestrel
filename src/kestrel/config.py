"""Load and validate all configuration; generate config/writing_style.md."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

from kestrel.models import Source, Taxonomy
from kestrel.store.excel import read_sources, read_kestrel_config, read_subscribers, read_austender_agencies


# ---------------------------------------------------------------------------
# Typed config objects
# ---------------------------------------------------------------------------

@dataclass
class ScheduleConfig:
    morning: str
    afternoon: str


@dataclass
class PathsConfig:
    data_dir: Path
    output_dir: Path
    assets_dir: Path


@dataclass
class RunConfig:
    global_time_budget_seconds: int
    per_source_timeout_seconds: int
    lookback_hours: dict[str, int]
    shipped_suppression_days: int


@dataclass
class SynthesisConfig:
    provider: str       # 'anthropic' | 'fallback'
    model: str          # Sonnet — enrich_item, top_line, watchpoints
    classify_model: str # Haiku  — bulk per-item classification
    max_retries: int


@dataclass
class BriefConfig:
    theme: str          # 'light' | 'dark'


@dataclass
class FilterConfig:
    min_rating_to_include: float = 3.0
    max_priority_items: int = 7
    max_per_body_subsection: int = 10
    max_body_headlines_total: int = 15
    watchpoints_min: int = 3
    watchpoints_max: int = 5
    title_similarity_threshold: float = 0.82
    w_impact: float = 0.4
    w_signal: float = 0.2
    w_trust: float = 0.2
    w_sentiment: float = 0.2
    escalation_boost: float = 1.0
    austender_min_award_value: int = 2_000_000


@dataclass
class EscalationRule:
    trigger: str
    keywords: list[str]
    action: str


@dataclass
class AudienceConfig:
    audience: str = "Defence & Industry"
    top_line_max_words: int = 150
    feedback_email: str = "product@quantrim.com"


@dataclass
class AppConfig:
    # yaml-level
    timezone: str
    schedule: ScheduleConfig
    paths: PathsConfig
    run: RunConfig
    synthesis: SynthesisConfig
    brief: BriefConfig
    # workbook-derived
    sources: list[Source]
    taxonomy: Taxonomy
    quotes: list[dict]
    filters: FilterConfig
    escalation_rules: list[EscalationRule]
    writing_style_rules: list[dict]
    audience: AudienceConfig
    subscribers: list[dict]
    austender_agencies: list[dict]   # [{name, category, active, notes}]
    # derived paths (absolute)
    project_root: Path


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _parse_filters(raw: dict[str, str]) -> FilterConfig:
    def f(k, default): return float(raw[k]) if k in raw else default
    def i(k, default): return int(float(raw[k])) if k in raw else default
    return FilterConfig(
        min_rating_to_include=f("min_rating_to_include", 3.0),
        max_priority_items=i("max_priority_items", 7),
        max_per_body_subsection=i("max_per_body_subsection", 10),
        max_body_headlines_total=i("max_body_headlines_total", 15),
        watchpoints_min=i("watchpoints_min", 3),
        watchpoints_max=i("watchpoints_max", 5),
        title_similarity_threshold=f("title_similarity_threshold", 0.82),
        w_impact=f("w_impact", 0.4),
        w_signal=f("w_signal", 0.2),
        w_trust=f("w_trust", 0.2),
        w_sentiment=f("w_sentiment", 0.2),
        escalation_boost=f("escalation_boost", 1.0),
        austender_min_award_value=i("austender_min_award_value", 2_000_000),
    )


def _parse_audience(raw: dict[str, str]) -> AudienceConfig:
    return AudienceConfig(
        audience=raw.get("audience", "Defence & Industry"),
        top_line_max_words=int(raw.get("top_line_max_words", "150")),
        feedback_email=raw.get("feedback_email", "product@quantrim.com"),
    )


def load_config(project_root: Path) -> AppConfig:
    yaml_path = project_root / "config" / "kestrel.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"kestrel.yaml not found at {yaml_path}")
    with open(yaml_path) as f:
        y = yaml.safe_load(f)

    paths = PathsConfig(
        data_dir=project_root / y["paths"]["data_dir"],
        output_dir=project_root / y["paths"]["output_dir"],
        assets_dir=project_root / y["paths"]["assets_dir"],
    )

    # Load workbooks
    source_path = paths.data_dir / "australian_defence_source_universe.xlsx"
    config_path = paths.data_dir / "kestrel_config.xlsx"
    sub_path = paths.data_dir / "subscribers.xlsx"

    raw_sources = read_sources(source_path)
    raw_config = read_kestrel_config(config_path)
    subscribers = read_subscribers(sub_path)
    austender_agencies = read_austender_agencies(config_path)

    sources = [Source(**s) for s in raw_sources]
    filters = _parse_filters(raw_config["filters"])
    audience = _parse_audience(raw_config["audience"])

    taxonomy = Taxonomy(
        kestrel_tags=[t["tag"] for t in raw_config["kestrel_tags"]],
        domain_tags=[t["tag"] for t in raw_config["domain_tags"]],
    )

    escalation_rules = [
        EscalationRule(trigger=r["trigger"], keywords=r["keywords"], action=r["action"])
        for r in raw_config["escalation"]
    ]

    run_cfg = y.get("run", {})
    cfg = AppConfig(
        timezone=y.get("timezone", "Australia/Sydney"),
        schedule=ScheduleConfig(
            morning=y["schedule"]["morning"],
            afternoon=y["schedule"]["afternoon"],
        ),
        paths=paths,
        run=RunConfig(
            global_time_budget_seconds=run_cfg.get("global_time_budget_seconds", 600),
            per_source_timeout_seconds=run_cfg.get("per_source_timeout_seconds", 20),
            lookback_hours={
                "morning": run_cfg.get("lookback_hours", {}).get("morning", 18),
                "afternoon": run_cfg.get("lookback_hours", {}).get("afternoon", 6),
            },
            shipped_suppression_days=y.get("run", {}).get("shipped_suppression_days", 5),
        ),
        synthesis=SynthesisConfig(
            provider=y["synthesis"].get("provider", "fallback"),
            model=y["synthesis"].get("model", "claude-sonnet-4-6"),
            classify_model=y["synthesis"].get(
                "classify_model",
                y["synthesis"].get("model", "claude-sonnet-4-6"),
            ),
            max_retries=y["synthesis"].get("max_retries", 3),
        ),
        brief=BriefConfig(theme=y["brief"].get("theme", "light")),
        sources=sources,
        taxonomy=taxonomy,
        quotes=raw_config["quotes"],
        filters=filters,
        escalation_rules=escalation_rules,
        writing_style_rules=raw_config["writing_style_rules"],
        audience=audience,
        subscribers=subscribers,
        austender_agencies=austender_agencies,
        project_root=project_root,
    )

    _regenerate_writing_style(cfg)
    return cfg


def _regenerate_writing_style(cfg: AppConfig) -> None:
    """Concatenate active writing-style rules into config/writing_style.md."""
    lines = ["# Writing style rules (generated from kestrel_config.xlsx)\n"]
    current_group = None
    for rule in cfg.writing_style_rules:
        if rule["group"] != current_group:
            current_group = rule["group"]
            lines.append(f"\n## {current_group}")
        lines.append(f"- {rule['rule']}")
    content = "\n".join(lines) + "\n"
    out = cfg.project_root / "config" / "writing_style.md"
    out.write_text(content, encoding="utf-8")


def select_sources(cfg: AppConfig, slot: str) -> list[Source]:
    """Filter + sort sources for the given slot."""
    active = [s for s in cfg.sources if s.active]
    slot_filtered = [
        s for s in active
        if (slot == "morning" and s.include_morning)
        or (slot == "afternoon" and s.include_afternoon)
    ]
    return sorted(slot_filtered, key=lambda s: (s.priority_tier, -s.signal_score, -s.trust_score))
