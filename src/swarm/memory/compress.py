"""Extractive context compression under a token budget.

Instead of an LLM summarizer (lossy, non-deterministic, expensive), the
compressor scores working-memory items by salience plus recency and keeps
the highest-scoring prefix that fits the budget, dropping the rest.  The
compression ratio is logged so operators can see how hard the budget
bit.  Trade-off discussed in the README ("extractive compression").
"""

from __future__ import annotations

from dataclasses import dataclass

from swarm.schemas import ClaimRecord


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~4 chars/token)."""
    return max(1, len(text) // 4)


@dataclass
class CompressionStats:
    original_count: int
    kept_count: int
    original_tokens: int
    kept_tokens: int
    compression_ratio: float  # kept / original tokens; 1.0 means no pruning

    def as_dict(self) -> dict[str, float]:
        return {
            "original_count": float(self.original_count),
            "kept_count": float(self.kept_count),
            "original_tokens": float(self.original_tokens),
            "kept_tokens": float(self.kept_tokens),
            "compression_ratio": self.compression_ratio,
        }


class ContextCompressor:
    def __init__(self, token_budget: int) -> None:
        self.token_budget = max(1, token_budget)

    def compress_claims(
        self, claims: list[ClaimRecord], *, recency_weight: float = 0.3
    ) -> tuple[list[ClaimRecord], CompressionStats]:
        """Keep the highest salience+recency claims whose tokens fit the budget.

        Recency is positional: later claims (fresher reads) get a small
        boost so the compressor does not systematically starve the last
        documents read.
        """
        original_tokens = sum(estimate_tokens(c.sentence) for c in claims)
        if original_tokens <= self.token_budget:
            stats = CompressionStats(
                original_count=len(claims),
                kept_count=len(claims),
                original_tokens=original_tokens,
                kept_tokens=original_tokens,
                compression_ratio=1.0,
            )
            return list(claims), stats

        scored = []
        for index, claim in enumerate(claims):
            recency = 1.0 / (1.0 + index)
            score = (1.0 - recency_weight) * claim.salience + recency_weight * recency
            scored.append((score, index, claim))
        scored.sort(key=lambda item: (-item[0], item[1]))

        kept_indices: list[int] = []
        used = 0
        for _, index, claim in scored:
            cost = estimate_tokens(claim.sentence)
            if used + cost > self.token_budget:
                continue
            used += cost
            kept_indices.append(index)
            if used >= self.token_budget:
                break

        kept = [claims[i] for i in sorted(kept_indices)]
        kept_tokens = sum(estimate_tokens(c.sentence) for c in kept)
        stats = CompressionStats(
            original_count=len(claims),
            kept_count=len(kept),
            original_tokens=original_tokens,
            kept_tokens=kept_tokens,
            compression_ratio=round(kept_tokens / max(1, original_tokens), 4),
        )
        return kept, stats
