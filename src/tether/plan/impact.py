"""Plan Phase: impact analysis.

Queries the ledger for features touching the target file, sends them
to Haiku, and returns a structured risk assessment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tether.ledger.queries import features_touching_file
from tether.ledger.schema import Feature, Ledger
from tether.prompts.templates import (
    IMPACT_SYSTEM,
    IMPACT_TOOL_NAME,
    IMPACT_TOOL_SCHEMA,
    IMPACT_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel

_RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
_ASK_THRESHOLD_ORDER = _RISK_ORDER


@dataclass
class FeatureRisk:
    feature_id: str
    feature_name: str
    level: str                  # none|low|medium|high
    reason: str
    mitigation: str | None = None


@dataclass
class ImpactResult:
    file_path: str
    intent: str
    affected_features: list[Feature]
    risks: list[FeatureRisk] = field(default_factory=list)
    overall_risk: str = "none"
    ask_user_required: bool = False

    @property
    def risk_distribution(self) -> dict[str, int]:
        """Count of features at each risk level."""
        dist: dict[str, int] = {"none": 0, "low": 0, "medium": 0, "high": 0}
        for r in self.risks:
            if r.level in dist:
                dist[r.level] += 1
        return dist

    @property
    def confidence(self) -> str:
        """
        Confidence in the impact prediction based on spread of risk levels.

        - high   : all risks land on ≤2 adjacent levels (tight cluster)
        - medium : risks span 3 levels
        - low    : risks span all 4 levels (high variance — Haiku is uncertain)
        """
        if not self.risks:
            return "high"
        levels_present = {_RISK_ORDER[r.level] for r in self.risks if r.level in _RISK_ORDER}
        span = max(levels_present) - min(levels_present)
        if span <= 1:
            return "high"
        if span == 2:
            return "medium"
        return "low"


def run_impact_analysis(
    file_path: str,
    intent: str,
    ledger: Ledger,
    model: WatcherModel,
    *,
    ask_threshold: str = "medium",
    diff: str = "",
) -> ImpactResult:
    """Run impact analysis for a planned change to file_path.

    Returns an ImpactResult with per-feature risks and an overall verdict.
    """
    affected = features_touching_file(ledger, file_path)

    result = ImpactResult(
        file_path=file_path,
        intent=intent,
        affected_features=affected,
    )

    if not affected:
        return result

    # Build YAML representation of affected features for the prompt
    affected_yaml = yaml.dump(
        [
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "files": f.files,
                "edge_cases": [
                    {"id": ec.id, "description": ec.description, "must_handle": ec.must_handle}
                    for ec in f.edge_cases
                ],
            }
            for f in affected
        ],
        default_flow_style=False,
        allow_unicode=True,
    )

    user_msg = IMPACT_USER_TEMPLATE.format(
        file_path=file_path,
        intent=intent,
        diff=diff or "(no diff provided)",
        affected_features_yaml=affected_yaml,
    )

    raw = model.check(
        system=IMPACT_SYSTEM,
        user=user_msg,
        tool_name=IMPACT_TOOL_NAME,
        tool_schema=IMPACT_TOOL_SCHEMA,
    )

    # Build a feature ID -> Feature map for lookups
    feature_map = {f.id: f for f in affected}

    risks: list[FeatureRisk] = []
    for risk_raw in raw.get("risks", []):
        if not isinstance(risk_raw, dict):
            continue

        fid = str(risk_raw.get("feature_id", ""))
        feature = feature_map.get(fid)
        level = str(risk_raw.get("level", "none"))
        risks.append(FeatureRisk(
            feature_id=fid,
            feature_name=feature.name if feature else fid,
            level=level,
            reason=str(risk_raw.get("reason", "")),
            mitigation=risk_raw.get("mitigation"),
        ))

    result.risks = sorted(risks, key=lambda r: _RISK_ORDER.get(r.level, 0), reverse=True)
    overall_risk = raw.get("overall_risk", "none")
    result.overall_risk = overall_risk if overall_risk in _RISK_ORDER else "none"

    # Compute ask_user_required from risks (never from model)
    threshold_val = _ASK_THRESHOLD_ORDER.get(ask_threshold, 2)
    result.ask_user_required = any(
        _RISK_ORDER.get(r.level, 0) >= threshold_val
        for r in result.risks
    )

    return result
