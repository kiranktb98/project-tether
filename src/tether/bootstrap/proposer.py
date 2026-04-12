"""Bootstrap Phase: send static scan chunks to Haiku for feature proposals."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

import yaml

from tether.bootstrap.scanner import FileSymbols, StaticScan
from tether.prompts.templates import (
    BOOTSTRAP_SYSTEM,
    BOOTSTRAP_TOOL_NAME,
    BOOTSTRAP_TOOL_SCHEMA,
    BOOTSTRAP_USER_TEMPLATE,
    EDGE_CASE_SYSTEM,
)
from tether.watcher_models.base import WatcherModel


@dataclass
class ProposedFeature:
    name: str
    description: str
    files: list[str]
    guessed_edge_cases: list[str] = field(default_factory=list)


def propose_features(
    scan: StaticScan,
    model: WatcherModel,
    *,
    max_files_per_chunk: int = 20,
) -> list[ProposedFeature]:
    """Chunk the static scan and ask Haiku to propose features.

    Returns a de-duplicated list of ProposedFeature objects.
    """
    chunks = scan.as_chunks(max_files_per_chunk)
    total = len(chunks)
    all_proposals: list[ProposedFeature] = []

    for idx, chunk in enumerate(chunks, start=1):
        static_yaml = yaml.dump(
            [f.to_yaml_dict() for f in chunk],
            default_flow_style=False,
            allow_unicode=True,
        )
        user_msg = BOOTSTRAP_USER_TEMPLATE.format(
            chunk_index=idx,
            total_chunks=total,
            static_scan_yaml=static_yaml,
        )

        result = model.check(
            system=BOOTSTRAP_SYSTEM,
            user=user_msg,
            tool_name=BOOTSTRAP_TOOL_NAME,
            tool_schema=BOOTSTRAP_TOOL_SCHEMA,
        )

        for raw in result.get("features", []):
            all_proposals.append(ProposedFeature(
                name=raw.get("name", "Unnamed feature"),
                description=raw.get("description", ""),
                files=raw.get("files", []),
                guessed_edge_cases=raw.get("guessed_edge_cases", []),
            ))

    return _deduplicate(all_proposals)


def _deduplicate(proposals: list[ProposedFeature]) -> list[ProposedFeature]:
    """Remove proposals that are near-duplicates by name similarity.

    Uses SequenceMatcher with a 0.80 threshold. Keeps the first occurrence.
    """
    kept: list[ProposedFeature] = []
    for candidate in proposals:
        if not _is_duplicate(candidate, kept):
            kept.append(candidate)
    return kept


def _is_duplicate(
    candidate: ProposedFeature,
    existing: list[ProposedFeature],
    threshold: float = 0.80,
) -> bool:
    for other in existing:
        ratio = SequenceMatcher(
            None, candidate.name.lower(), other.name.lower()
        ).ratio()
        if ratio >= threshold:
            return True
    return False
