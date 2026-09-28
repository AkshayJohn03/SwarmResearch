"""ReaderAgent: fetch doc -> clean -> chunk -> extract ClaimRecords.

The offline path is extractive sentence scoring (keyword overlap with the
task query + number/entity boosts); it never touches the LLM, so runs are
deterministic and free.  The LLM path is used only with a real client
(non-Echo) and offline mode off.

Provenance invariant: every claim's ``quote`` is an exact substring of
the source body -- ``char_start``/``char_end`` are computed against the
original text and verified before the claim is emitted.  If a quote
cannot be located in the source, the claim is dropped rather than kept
with fabricated coordinates.
"""

from __future__ import annotations

import json
import logging
import re

from swarm.agents.search import CorpusDoc, tokenize
from swarm.llm import EchoMockClient, LLMClient, Message
from swarm.memory.blackboard import Blackboard
from swarm.schemas import ClaimRecord, TaskNode
from swarm.settings import SwarmSettings

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_BULLET_PREFIX = re.compile(r"^[\s\-\*\d\.\)]*")
# Numbers not embedded in identifiers: "47 dB(A)" matches, the "7" in "XK-7"
# and the "11" in "KWS-11" do not (preceded by a letter, digit, dot or dash).
_NUMBER_RE = re.compile(r"(?<![\w.\-])(\d+(?:[.,]\d+)?)")
_UNIT_RE = re.compile(
    r"\s?(dB\(A\)|dB|kW|kg|mm|km|EUR|euros?|percent|%|years?|units?|metres?|hours?|hertz)"
)

# Ordered attribute vocabulary: first keyword hit wins.
ATTRIBUTE_KEYWORDS: list[tuple[str, str]] = [
    ("db(a)", "noise"),
    ("db(", "noise"),
    ("db", "noise"),
    ("sound pressure", "noise"),
    ("noise", "noise"),
    ("cop", "efficiency"),
    ("seasonal performance", "efficiency"),
    ("efficiency", "efficiency"),
    ("annual capacity", "production_capacity"),
    ("units per year", "production_capacity"),
    ("units annually", "production_capacity"),
    ("capacity of", "production_capacity"),
    ("warranty", "warranty"),
    ("gwp", "refrigerant_gwp"),
    ("refrigerant", "refrigerant"),
    ("propane", "refrigerant"),
    ("failure rate", "reliability"),
    ("downtime", "reliability"),
    ("weight", "weight"),
    ("price", "price"),
    ("cost", "price"),
]


def extract_attribute(sentence: str) -> str:
    lowered = sentence.lower()
    for keyword, attribute in ATTRIBUTE_KEYWORDS:
        if keyword in lowered:
            return attribute
    return ""


def extract_value(sentence: str) -> str:
    match = _NUMBER_RE.search(sentence)
    if not match:
        return ""
    unit = _UNIT_RE.match(sentence, match.end())
    return sentence[match.start() : unit.end() if unit else match.end()].strip()


def iter_sentences(body: str):
    """Yield (char_start, char_end, sentence) for prose sentences of ``body``.

    Headers, table lines and fence markers are treated as boilerplate and
    skipped.  Offsets are exact against ``body``.
    """
    offset = 0
    for line in body.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "```", "---")):
            continue
        prefix = _BULLET_PREFIX.match(line)
        content_start = line_start + prefix.end()
        content = line[prefix.end() :].rstrip("\n")
        if len(content.strip()) < 30:
            continue
        consumed = 0
        for piece in _SENTENCE_SPLIT.split(content):
            rel = content.find(piece, consumed)
            if rel < 0:
                consumed += len(piece)
                continue
            consumed = rel + len(piece)
            lead = len(piece) - len(piece.lstrip())
            trail = len(piece) - len(piece.rstrip())
            start = content_start + rel + lead
            end = content_start + rel + len(piece) - trail
            text = piece.strip()
            if len(text) >= 30 and body[start:end] == text:
                yield start, end, text


class ReaderAgent:
    def __init__(self, settings: SwarmSettings, llm: LLMClient | None, blackboard: Blackboard) -> None:
        self.settings = settings
        self.llm = llm
        self.blackboard = blackboard

    def _use_llm(self) -> bool:
        return (
            not self.settings.offline
            and self.llm is not None
            and not isinstance(self.llm, EchoMockClient)
        )

    async def read(self, doc: CorpusDoc, task: TaskNode) -> list[ClaimRecord]:
        if self._use_llm():
            claims = await self._llm_claims(doc, task)
        else:
            claims = self._extractive_claims(doc, task)
        verified = [c for c in claims if doc.text[c.char_start : c.char_end] == c.quote]
        dropped = len(claims) - len(verified)
        if dropped:
            logger.debug("reader dropped %d unverifiable claims from %s", dropped, doc.doc_id)
        return verified

    # -- offline extractive path -------------------------------------------

    def _extractive_claims(self, doc: CorpusDoc, task: TaskNode) -> list[ClaimRecord]:
        query_tokens = set(tokenize(task.query))
        candidates: list[tuple[float, int, int, str]] = []
        for start, end, sentence in iter_sentences(doc.text):
            tokens = set(tokenize(sentence))
            overlap = len(query_tokens & tokens)
            score = 2.0 * overlap / max(3, len(query_tokens))
            if _NUMBER_RE.search(sentence):
                score += 0.35
            if self.blackboard.match_entity(sentence):
                score += 0.30
            if score <= 0.25:
                continue
            candidates.append((round(score, 4), start, end, sentence))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        claims: list[ClaimRecord] = []
        for score, start, end, sentence in candidates[: self.settings.claims_per_doc]:
            lowered = sentence.lower()
            entity = self.blackboard.match_entity(sentence) or ""
            claims.append(
                ClaimRecord(
                    claim_id=f"c-{doc.doc_id}-{start}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    quote=sentence,
                    char_start=start,
                    char_end=end,
                    sentence=sentence,
                    entity=entity,
                    attribute=extract_attribute(lowered),
                    value=extract_value(sentence),
                    salience=min(1.0, score / 3.0),
                    task_id=task.id,
                )
            )
        return claims

    # -- LLM path ------------------------------------------------------------

    async def _llm_claims(self, doc: CorpusDoc, task: TaskNode) -> list[ClaimRecord]:
        assert self.llm is not None
        prompt = (
            "Extract up to 5 factual claims from the document below, relevant to: "
            f"{task.query}\nReturn ONLY a JSON array of objects with keys "
            '{"quote","entity","attribute","value","salience"} where quote is a '
            "verbatim sentence from the document.\n\nDOCUMENT:\n"
            f"{doc.text[:6000]}"
        )
        try:
            raw = await self.llm.complete([Message(role="user", content=prompt)])
        except Exception as exc:  # noqa: BLE001 - degrade to empty rather than crash
            logger.warning("LLM extraction failed for %s: %s", doc.doc_id, exc)
            return []
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end <= start:
            return []
        claims: list[ClaimRecord] = []
        try:
            items = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
        for item in items[: self.settings.claims_per_doc]:
            quote = str(item.get("quote", "")).strip()
            pos = doc.text.find(quote)
            if not quote or pos < 0:
                continue
            claims.append(
                ClaimRecord(
                    claim_id=f"c-{doc.doc_id}-{pos}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    quote=quote,
                    char_start=pos,
                    char_end=pos + len(quote),
                    sentence=quote,
                    entity=str(item.get("entity", "")),
                    attribute=str(item.get("attribute", "")),
                    value=str(item.get("value", "")),
                    salience=float(item.get("salience", 0.5)),
                    task_id=task.id,
                )
            )
        return claims
