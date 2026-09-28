"""Bundled corpus search: relevance, determinism, planted docs reachable."""

from __future__ import annotations

from swarm.agents.search import BundledCorpusBackend, tokenize


def test_corpus_loads_twenty_documents(backend: BundledCorpusBackend):
    assert backend.doc_count() == 20
    ids = {d.doc_id for d in backend.docs}
    assert "doc-01" in ids and "doc-20" in ids


def test_tokenize_drops_stopwords_and_short_tokens():
    tokens = tokenize("What is the noise level of the XK-7?")
    assert "the" not in tokens and "is" not in tokens
    assert "noise" in tokens and "xk" in tokens


def test_noise_query_ranks_both_planted_documents_high(backend: BundledCorpusBackend):
    import asyncio

    hits = asyncio.run(
        backend.search("XK-7 compressor module noise level dB measurement", max_docs=6)
    )
    top_ids = [h.doc_id for h in hits]
    assert "doc-02" in top_ids, "spec sheet (47 dB) not retrievable"
    assert "doc-03" in top_ids, "acoustic report (42 dB) not retrievable"
    assert hits[0].score >= hits[-1].score
    assert all(h.snippet for h in hits)


def test_search_is_deterministic(backend: BundledCorpusBackend):
    import asyncio

    q = "refrigerant propane safety"
    first = asyncio.run(backend.search(q, max_docs=5))
    second = asyncio.run(backend.search(q, max_docs=5))
    assert [h.doc_id for h in first] == [h.doc_id for h in second]


def test_get_returns_full_document_text(backend: BundledCorpusBackend):
    doc = backend.get("doc-03")
    assert "42 dB(A)" in doc.text
    assert doc.title.startswith("Acoustic")
    assert not doc.text.startswith("---"), "front matter must be stripped"


def test_custom_corpus_dir(tmp_path):
    import shutil
    from pathlib import Path

    import swarm.corpus as corpus_pkg

    copied = tmp_path / "corpus"
    shutil.copytree(Path(corpus_pkg.__file__).parent, copied)
    backend = BundledCorpusBackend(corpus_dir=copied)
    assert backend.doc_count() == 20
