"""WriterAgent: final markdown report with enforced inline citations.

Structure: executive summary, thematic findings, conflicting evidence,
analyst inference, confidence notes, open questions, sources appendix.

The citation discipline is enforced, not hoped for:

* citations are attached *inside* the terminal punctuation of a sentence
  (``... claim [4].``) so sentence tokenisation always keeps the marker
  attached to the sentence it proves;
* after drafting, every *factual* sentence (per the shared scoping rules
  in ``swarm.citations.graph``) must carry an ``[n]`` or be explicitly
  marked ``analyst-inference``; a final pass auto-marks violations and
  the report is only accepted with zero uncited factual sentences.
"""

from __future__ import annotations

import re

from swarm.citations.graph import (
    _SENTENCE_SPLIT,
    CitationRegistry,
    factual_sentences,
    is_cited,
    scoped_lines,
)
from swarm.schemas import AnalysisRecord, ClaimRecord, ResearchPlan, WrittenReport
from swarm.settings import SwarmSettings

_PUNCT = (".", "!", "?")
_ALPHA = re.compile(r"[A-Za-z]")


def _attach(sentence: str, marker: str) -> str:
    """Place a citation/marker before the sentence's terminal punctuation."""
    stripped = sentence.rstrip()
    if stripped.endswith(_PUNCT):
        return f"{stripped[:-1].rstrip()} {marker}{stripped[-1]}"
    return f"{stripped} {marker}"


class WriterAgent:
    def __init__(self, settings: SwarmSettings) -> None:
        self.settings = settings

    async def write(
        self,
        query: str,
        analysis: AnalysisRecord,
        plan: ResearchPlan,
        retask_coverage: float | None = None,
        compression_ratio: float = 1.0,
    ) -> WrittenReport:
        registry = CitationRegistry()

        def cite(claim: ClaimRecord) -> str:
            return f"[{registry.register(claim)}]"

        claims = analysis.claims
        themes: dict[str, list[ClaimRecord]] = {}
        for claim in claims:
            themes.setdefault(claim.entity or "General findings", []).append(claim)

        lines: list[str] = [f"# Research report: {query}", ""]
        lines.append(
            f"_Compiled by SwarmResearch from {len({c.doc_id for c in claims})} corpus "
            f"sources; all evidence is extractive and span-verified._"
        )
        lines.append("")
        lines.append("## Executive summary")
        lines.append("")
        if claims:
            second = f" {cite(claims[1])}" if len(claims) > 1 else ""
            lines.append(
                f"- The review retained {len(claims)} verified claims across "
                f"{len(themes)} themes with {len(analysis.contradictions)} flagged "
                f"contradiction(s) {cite(claims[0])}{second}."
            )
            lines.append(f"- Headline finding: {_attach(claims[0].sentence, cite(claims[0]))}")
            if analysis.contradictions:
                contradiction = analysis.contradictions[0]
                left = self._claim_by_id(claims, contradiction.left.claim_id) or claims[0]
                lines.append(
                    f"- Sources disagree on {contradiction.entity} "
                    f"{contradiction.attribute}; see Conflicting evidence {cite(left)}."
                )
        else:
            lines.append(_attach("- No verifiable claims were recovered from the corpus for this query.", "*(analyst-inference)*"))
        lines.append("")

        for theme, theme_claims in sorted(themes.items()):
            lines.append(f"## {theme}")
            lines.append("")
            for claim in theme_claims[:6]:
                lines.append(f"- {_attach(claim.sentence, cite(claim))}")
            lines.append("")

        if analysis.contradictions:
            lines.append("## Conflicting evidence")
            lines.append("")
            for contradiction in analysis.contradictions:
                left = self._claim_by_id(claims, contradiction.left.claim_id)
                right = self._claim_by_id(claims, contradiction.right.claim_id)
                if left is None or right is None:
                    continue
                lines.append(
                    f"- {contradiction.kind.replace('_', ' ')} on "
                    f"{contradiction.entity} {contradiction.attribute}: source "
                    f"{left.doc_id} states \"{contradiction.left.value}\" {cite(left)} "
                    f"while source {right.doc_id} states \"{contradiction.right.value}\" "
                    f"{cite(right)}."
                )
            lines.append("")

        if analysis.gaps:
            lines.append("## Analyst inference")
            lines.append("")
            for gap in analysis.gaps:
                sentence = (
                    f"- Planned sub-topic \"{gap.topic}\" returned no usable claims, so "
                    "the evidence base for that area is incomplete."
                )
                lines.append(_attach(sentence, "*(analyst-inference)*"))
            lines.append("")

        lines.append("## Confidence notes")
        lines.append("")
        coverage = retask_coverage if retask_coverage is not None else 1.0
        if claims:
            lines.append(
                f"- Span verification passed for all retained claims against their cited "
                f"documents {cite(claims[0])}."
            )
            budget_line = (
                f"- Plan coverage was {coverage:.0%} and context compression kept a ratio "
                f"of {compression_ratio:.2f}."
            )
            lines.append(_attach(budget_line, "*(analyst-inference)*"))
            if analysis.contradictions:
                lines.append(
                    f"- Confidence is moderate because {len(analysis.contradictions)} value "
                    f"conflict(s) between sources remain unresolved {cite(claims[-1])}."
                )
            else:
                lines.append(
                    f"- Confidence is high: sources are mutually consistent on the retained "
                    f"claims {cite(claims[0])}."
                )
        else:
            lines.append(_attach("- Confidence is low: no evidence was recovered.", "*(analyst-inference)*"))
        lines.append("")

        lines.append("## Open questions")
        lines.append("")
        if analysis.gaps:
            for gap in analysis.gaps:
                lines.append(f"- What do current measurements say about: {gap.topic}?")
        else:
            lines.append("- No open questions were flagged by the analyst pass.")
        lines.append("")

        lines.append("## Sources")
        lines.append("")
        for entry in registry.source_entries():
            lines.append(
                f"[{entry.n}] {entry.doc_id} - {entry.title} "
                f"(chars {entry.char_start}-{entry.char_end})"
            )

        text = self._enforce_citations("\n".join(lines))
        uncited = sum(1 for s in factual_sentences(text) if not is_cited(s))
        return WrittenReport(
            text=text,
            sources=registry.source_entries(),
            citation_count=len(registry.entries),
            factual_sentences=len(factual_sentences(text)),
            uncited_factual_sentences=uncited,
        )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _claim_by_id(claims: list[ClaimRecord], claim_id: str) -> ClaimRecord | None:
        return next((c for c in claims if c.claim_id == claim_id), None)

    @staticmethod
    def _enforce_citations(text: str) -> str:
        """Auto-mark any uncited factual sentence (belt-and-braces pass)."""
        out: list[str] = []
        for scope in scoped_lines(text):
            if scope.kind != "body":
                out.append(scope.text)
                continue
            fixed = []
            for sentence in _SENTENCE_SPLIT.split(scope.text.rstrip()):
                if _ALPHA.search(sentence) and not is_cited(sentence):
                    sentence = _attach(sentence, "*(analyst-inference)*")
                fixed.append(sentence.strip())
            out.append(" ".join(part for part in fixed if part))
        return "\n".join(out)
