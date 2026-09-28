"""SwarmResearch -- multiagent deep-research assistant on a hand-rolled
async orchestration runtime.

The orchestration layer (``swarm.orchestra``) has zero framework
dependencies; agents, memory, citations and the FastAPI surface build on
top of it.
"""

from swarm import schemas
from swarm.schemas import (
    AnalysisRecord,
    ClaimRecord,
    Contradiction,
    ResearchPlan,
    SearchHit,
    TaskKind,
    TaskNode,
)

__version__ = "0.1.0"

__all__ = [
    "AnalysisRecord",
    "ClaimRecord",
    "Contradiction",
    "ResearchPlan",
    "SearchHit",
    "TaskKind",
    "TaskNode",
    "schemas",
    "__version__",
]
