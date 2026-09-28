"""Shared typed store for claims, entities and task results.

The blackboard is the coordination substrate between agents: the reader
deposits claims, the analyst reads/canonicalizes them, the writer cites
from them.  Entity canonicalization keeps an alias index so "XK-7",
"component XK-7" and "xk7" all resolve to one canonical node.
"""

from __future__ import annotations

import re
from typing import Any

from swarm.schemas import ClaimRecord

# Seeded domain aliases for the bundled corpus.  Agents may register more
# at runtime via register_alias(); canonicalize() also learns new names.
ALIAS_SEEDS: dict[str, str] = {
    "xk7": "XK-7 compressor module",
    "xk-7": "XK-7 compressor module",
    "component xk-7": "XK-7 compressor module",
    "xk-7 module": "XK-7 compressor module",
    "xk-7 compressor": "XK-7 compressor module",
    "the xk-7": "XK-7 compressor module",
    "hx12": "HX-12 heat exchanger",
    "hx-12": "HX-12 heat exchanger",
    "hx-12 heat exchanger": "HX-12 heat exchanger",
    "r290": "R-290",
    "r-290": "R-290",
    "propane refrigerant": "R-290",
    "leipzig works": "Leipzig plant",
    "leipzig facility": "Leipzig plant",
    "leipzig plant": "Leipzig plant",
    "kaltwerk": "Kaltwerk",
    "kaltos": "KaltOS firmware",
    "kaltos firmware": "KaltOS firmware",
}


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class EntityRecord:
    __slots__ = ("canonical", "aliases", "mentions")

    def __init__(self, canonical: str) -> None:
        self.canonical = canonical
        self.aliases: set[str] = set()
        self.mentions = 0


class Blackboard:
    def __init__(self) -> None:
        self.claims: list[ClaimRecord] = []
        self.task_results: dict[str, Any] = {}
        self.metrics: dict[str, float] = {}
        self.entities: dict[str, EntityRecord] = {}
        self._claim_keys: set[tuple[str, int]] = set()
        self._alias_index: dict[str, str] = {}
        for alias, canonical in ALIAS_SEEDS.items():
            self.register_alias(alias, canonical)

    # -- aliases ---------------------------------------------------------

    def register_alias(self, alias: str, canonical: str) -> None:
        self._alias_index[normalize_name(alias)] = canonical
        record = self.entities.setdefault(canonical, EntityRecord(canonical))
        record.aliases.add(alias)

    def canonicalize(self, name: str) -> str:
        """Resolve a surface name to its canonical entity, learning if new."""
        key = normalize_name(name)
        canonical = self._alias_index.get(key)
        if canonical is None:
            canonical = name.strip()
            self.register_alias(name, canonical)
        self.entities[canonical].mentions += 1
        return canonical

    def match_entity(self, text: str) -> str | None:
        """Longest-alias scan over a sentence; returns the canonical entity."""
        haystack = normalize_name(text)
        if not haystack:
            return None
        for key in sorted(self._alias_index, key=len, reverse=True):
            if key and key in haystack:
                return self._alias_index[key]
        return None

    # -- claims ------------------------------------------------------------

    def add_claim(self, claim: ClaimRecord) -> bool:
        key = (claim.doc_id, claim.char_start)
        if key in self._claim_keys:
            return False
        self._claim_keys.add(key)
        self.claims.append(claim)
        if claim.entity:
            self.canonicalize(claim.entity)
        return True

    def add_claims(self, claims: list[ClaimRecord]) -> int:
        return sum(1 for claim in claims if self.add_claim(claim))

    def record_task(self, task_id: str, result: Any) -> None:
        self.task_results[task_id] = result
