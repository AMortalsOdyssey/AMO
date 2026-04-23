from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CharacterRecord:
    id: int
    name: str
    is_major: bool
    first_chapter: int | None
    relation_count: int = 0


@dataclass(frozen=True)
class AliasLink:
    alias_id: int
    alias_name: str
    canonical_id: int
    canonical_name: str
    relation_count: int = 0


@dataclass(frozen=True)
class MergeCandidate:
    alias_id: int
    alias_name: str
    canonical_id: int
    canonical_name: str
    reason: str


@dataclass(frozen=True)
class PruneCandidate:
    character_id: int
    character_name: str
    reason: str


@dataclass
class CleanupPlan:
    merges: list[MergeCandidate] = field(default_factory=list)
    prunes: list[PruneCandidate] = field(default_factory=list)
    skipped_aliases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merges": [asdict(item) for item in self.merges],
            "prunes": [asdict(item) for item in self.prunes],
            "skipped_aliases": self.skipped_aliases,
        }


class CleanupRules:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.hard_delete_patterns = [re.compile(p) for p in raw.get("hard_delete_regexes", [])]
        self.relation_prune_types = set(raw.get("relation_prune_types", []))
        self.manual_alias_map: dict[str, str] = raw.get("manual_alias_map", {})
        self.protected_names = set(raw.get("protected_names", []))

    @classmethod
    def load(cls, path: str | Path) -> "CleanupRules":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def is_protected(self, name: str) -> bool:
        return name in self.protected_names

    def is_low_value_name(self, name: str) -> bool:
        if not name:
            return True
        if len(name) <= 1:
            return True
        return any(pattern.search(name) for pattern in self.hard_delete_patterns)

    def should_prune_relation_type(self, relation_type: str | None) -> bool:
        if not relation_type:
            return False
        return relation_type in self.relation_prune_types


def _prefer_candidate(current: MergeCandidate | None, incoming: MergeCandidate) -> MergeCandidate:
    if current is None:
        return incoming
    if current.reason == "manual_alias_map":
        return current
    if incoming.reason == "manual_alias_map":
        return incoming
    return current


def _canonical_score(
    char: CharacterRecord,
    *,
    rules: CleanupRules,
    incoming_count: int,
    manual_target_count: int,
) -> tuple[int, int, int, int, int, int, int, int]:
    first_chapter = char.first_chapter if char.first_chapter is not None else 10**9
    return (
        manual_target_count,
        1 if rules.is_protected(char.name) else 0,
        0 if rules.is_low_value_name(char.name) else 1,
        1 if char.is_major else 0,
        incoming_count,
        char.relation_count,
        -first_chapter,
        len(char.name),
    )


def _collapse_merge_components(
    merge_by_alias_id: dict[int, MergeCandidate],
    by_id: dict[int, CharacterRecord],
    rules: CleanupRules,
) -> dict[int, MergeCandidate]:
    if not merge_by_alias_id:
        return {}

    adjacency: dict[int, set[int]] = {}
    incoming_count: dict[int, int] = {}
    manual_target_count: dict[int, int] = {}

    for merge in merge_by_alias_id.values():
        adjacency.setdefault(merge.alias_id, set()).add(merge.canonical_id)
        adjacency.setdefault(merge.canonical_id, set()).add(merge.alias_id)
        incoming_count[merge.canonical_id] = incoming_count.get(merge.canonical_id, 0) + 1
        if merge.reason == "manual_alias_map":
            manual_target_count[merge.canonical_id] = manual_target_count.get(merge.canonical_id, 0) + 1

    collapsed: dict[int, MergeCandidate] = {}
    seen: set[int] = set()

    for start_id in adjacency:
        if start_id in seen:
            continue
        stack = [start_id]
        component: set[int] = set()
        while stack:
            current_id = stack.pop()
            if current_id in component:
                continue
            component.add(current_id)
            seen.add(current_id)
            stack.extend(adjacency.get(current_id, ()))

        ranked = sorted(
            (by_id[cid] for cid in component if cid in by_id),
            key=lambda char: _canonical_score(
                char,
                rules=rules,
                incoming_count=incoming_count.get(char.id, 0),
                manual_target_count=manual_target_count.get(char.id, 0),
            ),
            reverse=True,
        )
        if not ranked:
            continue
        canonical = ranked[0]
        for cid in component:
            if cid == canonical.id:
                continue
            alias_char = by_id.get(cid)
            if alias_char is None:
                continue
            source = merge_by_alias_id.get(cid)
            reason = source.reason if source else "alias_component_canonicalized"
            collapsed[cid] = MergeCandidate(
                alias_id=alias_char.id,
                alias_name=alias_char.name,
                canonical_id=canonical.id,
                canonical_name=canonical.name,
                reason=reason,
            )

    return collapsed


def build_cleanup_plan(
    characters: list[CharacterRecord],
    alias_links: list[AliasLink],
    rules: CleanupRules,
) -> CleanupPlan:
    by_name = {char.name: char for char in characters}
    by_id = {char.id: char for char in characters}
    merge_by_alias_id: dict[int, MergeCandidate] = {}
    skipped_aliases: list[dict[str, Any]] = []

    grouped_links: dict[int, list[AliasLink]] = {}
    for link in alias_links:
        grouped_links.setdefault(link.alias_id, []).append(link)

    for alias_id, links in grouped_links.items():
        alias_name = links[0].alias_name
        if rules.is_protected(alias_name):
            skipped_aliases.append({
                "alias_id": alias_id,
                "alias_name": alias_name,
                "reason": "protected_name",
            })
            continue
        canonical_options = {(link.canonical_id, link.canonical_name) for link in links}
        if len(canonical_options) == 1:
            canonical_id, canonical_name = next(iter(canonical_options))
            if rules.is_low_value_name(canonical_name) and not rules.is_protected(canonical_name):
                skipped_aliases.append({
                    "alias_id": alias_id,
                    "alias_name": alias_name,
                    "reason": "low_value_canonical_target",
                    "targets": [{"id": canonical_id, "name": canonical_name}],
                })
                continue
            merge_by_alias_id[alias_id] = _prefer_candidate(
                merge_by_alias_id.get(alias_id),
                MergeCandidate(
                    alias_id=alias_id,
                    alias_name=alias_name,
                    canonical_id=canonical_id,
                    canonical_name=canonical_name,
                    reason="character_alias_exact_match",
                ),
            )
            continue
        skipped_aliases.append({
            "alias_id": alias_id,
            "alias_name": alias_name,
            "reason": "ambiguous_alias_targets",
            "targets": sorted(
                ({"id": cid, "name": cname} for cid, cname in canonical_options),
                key=lambda item: (item["name"], item["id"]),
            ),
        })

    for alias_name, canonical_name in rules.manual_alias_map.items():
        alias_char = by_name.get(alias_name)
        canonical_char = by_name.get(canonical_name)
        if not alias_char or not canonical_char or alias_char.id == canonical_char.id:
            continue
        merge_by_alias_id[alias_char.id] = _prefer_candidate(
            merge_by_alias_id.get(alias_char.id),
            MergeCandidate(
                alias_id=alias_char.id,
                alias_name=alias_char.name,
                canonical_id=canonical_char.id,
                canonical_name=canonical_char.name,
                reason="manual_alias_map",
            ),
        )

    merge_by_alias_id = _collapse_merge_components(merge_by_alias_id, by_id, rules)

    merge_alias_ids = set(merge_by_alias_id.keys())
    protected_canonical_names = {merge.canonical_name for merge in merge_by_alias_id.values()}

    prunes: list[PruneCandidate] = []
    for char in characters:
        if char.id in merge_alias_ids:
            continue
        if rules.is_protected(char.name):
            continue
        if char.name in protected_canonical_names:
            continue
        if rules.is_low_value_name(char.name):
            prunes.append(
                PruneCandidate(
                    character_id=char.id,
                    character_name=char.name,
                    reason="low_value_name_rule",
                )
            )

    return CleanupPlan(
        merges=sorted(merge_by_alias_id.values(), key=lambda item: (item.alias_name, item.canonical_name)),
        prunes=sorted(prunes, key=lambda item: item.character_name),
        skipped_aliases=sorted(skipped_aliases, key=lambda item: item["alias_name"]),
    )


def dump_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
