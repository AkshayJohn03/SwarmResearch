"""ReaderAgent: span-exact extractive claims, entity/attribute tagging."""

from __future__ import annotations

import asyncio

from swarm.agents.reader import ReaderAgent, iter_sentences
from swarm.llm import EchoMockClient
from swarm.memory.blackboard import Blackboard
from swarm.schemas import TaskKind, TaskNode


def make_reader(settings) -> ReaderAgent:
    return ReaderAgent(settings, EchoMockClient(), Blackboard())


NOISE_TASK = TaskNode(id="search-0", kind=TaskKind.SEARCH, query="XK-7 compressor module noise level measurement")


def test_reader_extracts_span_exact_claims(settings, backend):
    doc = backend.get("doc-03")
    claims = asyncio.run(make_reader(settings).read(doc, NOISE_TASK))
    assert claims, "no claims extracted from the acoustic report"
    for claim in claims:
        assert doc.text[claim.char_start : claim.char_end] == claim.quote
        assert claim.doc_id == "doc-03"
        assert claim.task_id == "search-0"


def test_reader_tags_entity_and_noise_attribute(settings, backend):
    claims = asyncio.run(make_reader(settings).read(backend.get("doc-03"), NOISE_TASK))
    planted = [c for c in claims if "42" in c.value]
    assert planted, "planted 42 dB(A) sentence was not extracted"
    assert planted[0].entity == "XK-7 compressor module"
    assert planted[0].attribute == "noise"


def test_reader_uses_no_llm_offline(settings, backend):
    llm = EchoMockClient()
    claims = asyncio.run(
        ReaderAgent(settings, llm, Blackboard()).read(backend.get("doc-02"), NOISE_TASK)
    )
    assert claims
    assert llm.calls == 0, "offline extractive path must not call the LLM"


def test_reader_respects_claims_per_doc(settings, backend):
    claims = asyncio.run(make_reader(settings).read(backend.get("doc-01"), NOISE_TASK))
    assert len(claims) <= settings.claims_per_doc


def test_iter_sentences_offsets_are_exact():
    body = "# Header to skip\n\nThis is a long enough first sentence for the filter. And a second one follows it right here!\n- Bullet with a long enough tail to pass the length filter too.\n"
    spans = [(s, e, text) for s, e, text in iter_sentences(body)]
    assert spans, "expected prose sentences"
    for start, end, text in spans:
        assert body[start:end] == text
    assert not any(text.startswith("#") for _, _, text in spans)
