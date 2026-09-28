"""Blackboard canonicalization and claim dedupe; compressor budget."""

from __future__ import annotations

from swarm.memory.blackboard import Blackboard
from swarm.memory.compress import ContextCompressor, estimate_tokens
from swarm.schemas import ClaimRecord


def make_claim(i: int, sentence: str, salience: float = 0.5) -> ClaimRecord:
    return ClaimRecord(
        claim_id=f"c{i}",
        doc_id="doc-01",
        doc_title="t",
        quote=sentence,
        char_start=i,
        char_end=i + len(sentence),
        sentence=sentence,
        salience=salience,
    )


def test_alias_canonicalization_maps_variants_together():
    board = Blackboard()
    assert board.canonicalize("XK-7") == "XK-7 compressor module"
    assert board.canonicalize("component XK-7") == "XK-7 compressor module"
    assert board.canonicalize("xk7") == "XK-7 compressor module"
    assert board.canonicalize("r290") == "R-290"
    assert board.canonicalize("Leipzig works") == "Leipzig plant"


def test_match_entity_scans_sentences():
    board = Blackboard()
    sentence = "The service team replaced the HX-12 heat exchanger within ninety minutes."
    assert board.match_entity(sentence) == "HX-12 heat exchanger"
    assert board.match_entity("Nothing relevant here at all in this text.") is None


def test_unknown_entities_learn_canonical_form():
    board = Blackboard()
    canonical = board.canonicalize("Falcon Valve")
    assert canonical == "Falcon Valve"
    assert board.canonicalize("falcon valve") == "Falcon Valve"


def test_add_claim_dedupes_on_doc_and_span():
    board = Blackboard()
    first = make_claim(0, "sentence one for the blackboard dedupe test.")
    duplicate = first.model_copy()
    other = make_claim(1, "a different sentence at a different offset entirely.")
    assert board.add_claim(first) is True
    assert board.add_claim(duplicate) is False
    assert board.add_claim(other) is True
    assert len(board.claims) == 2


def test_compressor_respects_token_budget():
    budget = 100
    compressor = ContextCompressor(budget)
    claims = [
        make_claim(i, f"Claim number {i} " + "word " * 12, salience=i / 20.0)
        for i in range(30)
    ]
    kept, stats = compressor.compress_claims(claims)
    assert stats.original_tokens > budget
    assert stats.kept_tokens <= budget
    assert len(kept) < len(claims)
    assert stats.compression_ratio < 1.0
    kept_ids = {c.claim_id for c in kept}
    assert kept_ids.issubset({c.claim_id for c in claims})


def test_compressor_noop_when_under_budget():
    compressor = ContextCompressor(10_000)
    claims = [make_claim(i, f"Short claim {i} with modest length.") for i in range(5)]
    kept, stats = compressor.compress_claims(claims)
    assert len(kept) == len(claims)
    assert stats.compression_ratio == 1.0


def test_estimate_tokens_is_deterministic_and_positive():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcdefgh") == 2
