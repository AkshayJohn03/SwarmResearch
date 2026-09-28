"""Shared fixtures. Everything runs offline: no test touches the network."""

from __future__ import annotations

import asyncio

import pytest

from swarm.agents.search import BundledCorpusBackend
from swarm.orchestra.checkpoint import CheckpointStore
from swarm.pipeline import ResearchPipeline, ResearchRunResult
from swarm.settings import SwarmSettings

QUERY = (
    "What is the noise level of the XK-7 compressor module and how reliable is it in the field?"
)


@pytest.fixture(scope="session")
def settings() -> SwarmSettings:
    return SwarmSettings(
        offline=True,
        max_concurrency=3,
        max_docs_per_task=4,
        claims_per_doc=5,
        token_budget=6000,
        coverage_threshold=0.8,
        _env_file=None,
    )


@pytest.fixture(scope="session")
def backend() -> BundledCorpusBackend:
    return BundledCorpusBackend()


@pytest.fixture(scope="module")
def offline_run(settings) -> ResearchRunResult:
    """One full offline research run shared by e2e/metrics/writer tests."""

    async def go() -> ResearchRunResult:
        pipeline = ResearchPipeline(settings, checkpoint=CheckpointStore(":memory:"))
        return await pipeline.run(QUERY)

    return asyncio.run(go())
