"""Shared pydantic contracts flowing between agents, memory and the runtime.

Keeping these in one module makes the "typed channels" story real: node
outputs are validated models, not loose dicts.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    doc_id: str
    title: str
    score: float
    snippet: str


class ClaimRecord(BaseModel):
    """One extractive claim, pinned to an exact character span of its source.

    ``quote == doc_text[char_start:char_end]`` is the provenance invariant;
    the critic verifies it and the citation metrics depend on it.
    """

    claim_id: str
    doc_id: str
    doc_title: str
    quote: str
    char_start: int
    char_end: int
    sentence: str
    entity: str = ""
    attribute: str = ""
    value: str = ""
    salience: float = 0.0
    task_id: str = ""


class ContradictionSide(BaseModel):
    value: str
    doc_id: str
    quote: str
    claim_id: str


class Contradiction(BaseModel):
    entity: str
    attribute: str
    kind: str  # "numeric_mismatch" | "negation_conflict"
    left: ContradictionSide
    right: ContradictionSide


class GapNote(BaseModel):
    topic: str
    reason: str


class AnalysisRecord(BaseModel):
    claims: list[ClaimRecord]
    entities: list[str] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    gaps: list[GapNote] = Field(default_factory=list)
    dropped_duplicates: int = 0


class TaskKind(StrEnum):
    SEARCH = "search"
    READ = "read"
    ANALYZE = "analyze"
    CRITIC = "critic"
    WRITE = "write"
    GAPFILL = "gapfill"


class TaskNode(BaseModel):
    """Planner-level task; compiled 1:1 into runtime graph nodes."""

    id: str
    kind: TaskKind
    query: str = ""
    depends_on: list[str] = Field(default_factory=list)
    max_docs: int = 4
    max_tokens: int = 2000
    params: dict[str, Any] = Field(default_factory=dict)


class ResearchPlan(BaseModel):
    query: str
    tasks: list[TaskNode]
    total_token_budget: int = 6000

    def tasks_of_kind(self, kind: TaskKind) -> list[TaskNode]:
        return [t for t in self.tasks if t.kind == kind]

    def search_tasks(self) -> list[TaskNode]:
        return self.tasks_of_kind(TaskKind.SEARCH)

    def read_tasks(self) -> list[TaskNode]:
        return self.tasks_of_kind(TaskKind.READ)

    def get(self, task_id: str) -> TaskNode | None:
        return next((t for t in self.tasks if t.id == task_id), None)


class RetaskPlan(BaseModel):
    reason: str
    coverage: float
    new_tasks: list[TaskNode] = Field(default_factory=list)


class CriticDecision(BaseModel):
    route: str  # "finalize" | "gapfill"
    coverage: float
    unsupported_claims: list[str] = Field(default_factory=list)
    retask: RetaskPlan
    reason: str


class SourceEntry(BaseModel):
    n: int
    doc_id: str
    title: str
    char_start: int
    char_end: int


class WrittenReport(BaseModel):
    text: str
    sources: list[SourceEntry] = Field(default_factory=list)
    citation_count: int = 0
    factual_sentences: int = 0
    uncited_factual_sentences: int = 0


class ResearchMetrics(BaseModel):
    hallucination_rate: float
    citation_coverage: float
    total_claims: int
    valid_claims: int
    contradictions: int
    plan_coverage: float
    compression_ratio: float = 1.0
