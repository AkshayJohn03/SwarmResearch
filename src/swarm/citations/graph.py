"""Citation provenance: registry, span verification, report-level metrics.

Key metrics:

* ``hallucination_rate`` = claims lacking valid provenance / total claims,
  where *valid provenance* means ``doc_text[char_start:char_end] == quote``
  (the extractive invariant).  0.0 is the only acceptable steady state.
* ``citation_coverage`` = cited factual sentences / total factual sentences
  in the final report, under the scoping rules in :func:`scoped_lines`.

Report scoping rules (shared by the writer's enforcement pass and these
metrics, so they can never disagree):

* headings (``#...``) are structure, not assertions;
* the ``## Sources`` appendix and lines starting with ``[`` are citation
  *targets*, not claims;
* the ``## Open questions`` section is interrogative, not factual;
* lines starting with ``_`` are italic metadata.
Everything else is a factual sentence and must carry ``[n]`` or the
``analyst-inference`` marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from swarm.schemas import ClaimRecord, SourceEntry

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CITATION_RE = re.compile(r"\[\d+\]")
_INFERENCE_MARK = "analyst-inference"


@dataclass
class LineScope:
    text: str
    kind: str  # "heading" | "blank" | "sources" | "open_questions" | "meta" | "body"


def scoped_lines(report: str) -> list[LineScope]:
    scopes: list[LineScope] = []
    current_skip: str | None = None
    for raw in report.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            lowered = stripped.lower()
            if lowered.startswith("## sources"):
                current_skip = "sources"
            elif lowered.startswith("## open questions"):
                current_skip = "open_questions"
            else:
                current_skip = None
            scopes.append(LineScope(raw, "heading"))
        elif not stripped:
            scopes.append(LineScope(raw, "blank"))
        elif current_skip == "sources":
            scopes.append(LineScope(raw, "sources"))
        elif current_skip == "open_questions":
            scopes.append(LineScope(raw, "open_questions"))
        elif stripped.startswith("[") or stripped.startswith("_"):
            scopes.append(LineScope(raw, "meta"))
        else:
            scopes.append(LineScope(raw, "body"))
    return scopes


def factual_sentences(report: str) -> list[str]:
    sentences: list[str] = []
    for scope in scoped_lines(report):
        if scope.kind != "body":
            continue
        for sentence in _SENTENCE_SPLIT.split(scope.text.strip()):
            if re.search(r"[A-Za-z]", sentence):
                sentences.append(sentence.strip())
    return sentences


def is_cited(sentence: str) -> bool:
    return bool(_CITATION_RE.search(sentence)) or _INFERENCE_MARK in sentence


class CitationRegistry:
    """Assigns stable 1-based citation numbers to claims, dedup by claim_id."""

    def __init__(self) -> None:
        self._entries: list[ClaimRecord] = []
        self._by_id: dict[str, int] = {}

    def register(self, claim: ClaimRecord) -> int:
        if claim.claim_id in self._by_id:
            return self._by_id[claim.claim_id]
        self._entries.append(claim)
        number = len(self._entries)
        self._by_id[claim.claim_id] = number
        return number

    def number_for(self, claim_id: str) -> int | None:
        return self._by_id.get(claim_id)

    @property
    def entries(self) -> list[ClaimRecord]:
        return list(self._entries)

    def source_entries(self) -> list[SourceEntry]:
        return [
            SourceEntry(
                n=i + 1,
                doc_id=claim.doc_id,
                title=claim.doc_title,
                char_start=claim.char_start,
                char_end=claim.char_end,
            )
            for i, claim in enumerate(self._entries)
        ]


class CitationGraph:
    """Static helpers computing provenance metrics."""

    @staticmethod
    def claim_metrics(claims: list[ClaimRecord], docs_text: dict[str, str]) -> dict[str, float]:
        total = len(claims)
        valid = sum(
            1 for c in claims if docs_text.get(c.doc_id, "")[c.char_start : c.char_end] == c.quote
        )
        rate = 0.0 if total == 0 else round(1.0 - valid / total, 6)
        return {
            "total_claims": float(total),
            "valid_claims": float(valid),
            "hallucination_rate": rate,
        }

    @staticmethod
    def report_citation_coverage(report: str) -> float:
        sentences = factual_sentences(report)
        if not sentences:
            return 1.0
        cited = sum(1 for s in sentences if is_cited(s))
        return cited / len(sentences)
