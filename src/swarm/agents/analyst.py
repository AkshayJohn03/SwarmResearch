"""AnalystAgent: merge claim tables across docs, dedupe, find contradictions.

* Dedupe uses token-set Jaccard over binary numpy vectors (threshold 0.85);
  the higher-salience claim survives.
* Contradiction detection groups claims by (canonical entity, attribute)
  and flags either a numeric mismatch (e.g. 42 vs 47 dB(A)) or a negation
  conflict for boolean-ish attributes.  Both sides keep full provenance.
* Knowledge gaps are planned sub-topics that yielded zero claims.
"""

from __future__ import annotations

import re

import numpy as np

from swarm.schemas import (
    AnalysisRecord,
    ClaimRecord,
    Contradiction,
    ContradictionSide,
    GapNote,
    ResearchPlan,
)
from swarm.settings import SwarmSettings

# Same boundary rule as the reader's value extractor: skip digits embedded
# in identifiers like "XK-7" or "KWS-11".
_NUMBER_RE = re.compile(r"(?<![\w.\-])[-+]?\d+(?:[.,]\d+)?")
_NEGATORS = ("not ", "no ", "never ", "cannot ", "without ", "fails to ", "failed to ")
# Attributes where a negated vs non-negated phrasing is itself the conflict.
# Deliberately conservative: for attributes like "refrigerant", a negator in
# the sentence ("the F-gas quota does not apply to the refrigerant charge")
# usually negates something else, so lexical polarity detection is too noisy.
_BOOLEAN_ATTRS = {"warranty", "reliability"}

_JACCARD_THRESHOLD = 0.85


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    return float(match.group().replace(",", ""))


class AnalystAgent:
    def __init__(self, settings: SwarmSettings) -> None:
        self.settings = settings

    async def analyze(self, claims: list[ClaimRecord], plan: ResearchPlan) -> AnalysisRecord:
        kept, dropped = self._dedupe(claims)
        entities = sorted({c.entity for c in kept if c.entity})
        contradictions = self._contradictions(kept)
        gaps = self._gaps(kept, plan)
        return AnalysisRecord(
            claims=kept,
            entities=entities,
            contradictions=contradictions,
            gaps=gaps,
            dropped_duplicates=dropped,
        )

    # -- dedupe -----------------------------------------------------------

    @staticmethod
    def _dedupe(claims: list[ClaimRecord]) -> tuple[list[ClaimRecord], int]:
        if not claims:
            return [], 0
        vocab: dict[str, int] = {}
        token_sets = []
        for claim in claims:
            tokens = set(re.findall(r"[a-z0-9]+", claim.quote.lower()))
            token_sets.append(tokens)
            for token in tokens:
                vocab.setdefault(token, len(vocab))
        matrix = np.zeros((len(claims), len(vocab)), dtype=np.float32)
        for row, tokens in enumerate(token_sets):
            for token in tokens:
                matrix[row, vocab[token]] = 1.0

        dropped = 0
        keep: list[ClaimRecord] = []
        kept_rows: list[int] = []
        for row, claim in enumerate(claims):
            duplicate_of = None
            for other in kept_rows:
                intersection = float(np.logical_and(matrix[row], matrix[other]).sum())
                union = float(np.logical_or(matrix[row], matrix[other]).sum())
                if union and intersection / union >= _JACCARD_THRESHOLD:
                    duplicate_of = other
                    break
            if duplicate_of is not None:
                dropped += 1
                if claim.salience > claims[duplicate_of].salience:
                    keep[kept_rows.index(duplicate_of)] = claim
                continue
            keep.append(claim)
            kept_rows.append(row)
        return keep, dropped

    # -- contradictions ------------------------------------------------------

    def _contradictions(self, claims: list[ClaimRecord]) -> list[Contradiction]:
        groups: dict[tuple[str, str], list[ClaimRecord]] = {}
        for claim in claims:
            if claim.entity and claim.attribute:
                groups.setdefault((claim.entity, claim.attribute), []).append(claim)

        contradictions: list[Contradiction] = []
        for (entity, attribute), members in sorted(groups.items()):
            numeric: list[tuple[float, ClaimRecord]] = []
            for claim in members:
                number = _first_number(claim.value or claim.sentence)
                if number is not None:
                    numeric.append((number, claim))
            distinct = sorted({round(n, 6) for n, _ in numeric})
            if len(distinct) >= 2:
                first_number, first_claim = numeric[0]
                other_claim = next(
                    (c for n, c in numeric if abs(n - first_number) > 1e-9), None
                )
                if other_claim is not None:
                    contradictions.append(
                        Contradiction(
                            entity=entity,
                            attribute=attribute,
                            kind="numeric_mismatch",
                            left=self._side(first_claim),
                            right=self._side(other_claim),
                        )
                    )
                continue
            if attribute in _BOOLEAN_ATTRS:
                negated = [c for c in members if self._is_negated_on(c.sentence, attribute)]
                plain = [c for c in members if not self._is_negated_on(c.sentence, attribute)]
                if negated and plain:
                    contradictions.append(
                        Contradiction(
                            entity=entity,
                            attribute=attribute,
                            kind="negation_conflict",
                            left=self._side(plain[0]),
                            right=self._side(negated[0]),
                        )
                    )
        return contradictions

    @staticmethod
    def _side(claim: ClaimRecord) -> ContradictionSide:
        number = _first_number(claim.value or claim.sentence)
        value = claim.value or (str(number) if number is not None else "")
        return ContradictionSide(
            value=value, doc_id=claim.doc_id, quote=claim.quote, claim_id=claim.claim_id
        )

    @staticmethod
    def _is_negated_on(sentence: str, attribute: str) -> bool:
        """True only when a negator sits near the attribute keyword.

        A sentence like "wide availability without quota restrictions" must
        not flip the polarity of a distant "refrigerant" mention, so the
        negator has to appear within +/- 40 characters of the keyword.
        """
        lowered = sentence.lower()
        idx = lowered.find(attribute)
        if idx < 0:
            return False  # keyword paraphrased away: conservatively not negated
        window = lowered[max(0, idx - 40) : idx + len(attribute) + 40]
        return any(negator in window for negator in _NEGATORS)

    # -- gaps ------------------------------------------------------------------

    def _gaps(self, claims: list[ClaimRecord], plan: ResearchPlan) -> list[GapNote]:
        covered = {c.task_id for c in claims}
        return [
            GapNote(
                topic=task.query,
                reason=f"no claims extracted for planned sub-topic {task.id}",
            )
            for task in plan.search_tasks()
            if task.id not in covered
        ]
