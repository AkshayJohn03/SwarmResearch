"""Search backends.

:class:`BundledCorpusBackend` performs deterministic full-text scoring
(TF x IDF over a stopword-filtered vocabulary) across ~20 bundled
markdown documents -- the default, fully offline path.
:class:`WebSearchBackend` is opt-in via ``SWARM_WEB_SEARCH_ENDPOINT``
and is never touched by the test suite.
"""

from __future__ import annotations

import importlib.resources
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx
import yaml

from swarm.schemas import SearchHit
from swarm.settings import SwarmSettings

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that the "
    "their there these this to was were what which with without how does do when "
    "while can may will would should also than then them they".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


@dataclass
class CorpusDoc:
    doc_id: str
    title: str
    date: str
    tags: list[str]
    text: str  # body only (front matter stripped); claim spans refer to this


@dataclass
class _IndexedDoc:
    doc: CorpusDoc
    term_freq: dict[str, int] = field(default_factory=dict)


class SearchBackend(Protocol):
    async def search(self, query: str, max_docs: int) -> list[SearchHit]: ...


def _parse_markdown_doc(raw: str) -> CorpusDoc:
    header: dict = {}
    body = raw
    if raw.lstrip("\ufeff").startswith("---"):
        lines = raw.splitlines(keepends=True)
        fence_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]
        if len(fence_indices) >= 2:
            start, end = fence_indices[0], fence_indices[1]
            loaded = yaml.safe_load("".join(lines[start + 1 : end])) or {}
            if isinstance(loaded, dict):
                header = loaded
            body = "".join(lines[end + 1 :])
    return CorpusDoc(
        doc_id=str(header.get("doc_id", "")),
        title=str(header.get("title", "")),
        date=str(header.get("date", "")),
        tags=[str(t) for t in (header.get("tags") or [])],
        text=body.strip("\n"),
    )


class BundledCorpusBackend:
    """Full-text search over the bundled (or a custom) markdown corpus."""

    def __init__(self, corpus_dir: str | Path | None = None) -> None:
        self._docs: dict[str, CorpusDoc] = {}
        self._index: dict[str, _IndexedDoc] = {}
        self._df: dict[str, int] = {}
        if corpus_dir is not None:
            raws = [p.read_text(encoding="utf-8") for p in sorted(Path(corpus_dir).glob("*.md"))]
        else:
            trav = importlib.resources.files("swarm.corpus")
            raws = [
                (trav / name).read_text(encoding="utf-8")
                for name in sorted(entry.name for entry in trav.iterdir())
                if name.endswith(".md")
            ]
        for raw in raws:
            doc = _parse_markdown_doc(raw)
            if not doc.doc_id:
                continue
            self._docs[doc.doc_id] = doc
            indexed = _IndexedDoc(doc=doc)
            for term in tokenize(f"{doc.title} {doc.text}"):
                indexed.term_freq[term] = indexed.term_freq.get(term, 0) + 1
            for term in indexed.term_freq:
                self._df[term] = self._df.get(term, 0) + 1
            self._index[doc.doc_id] = indexed

    # -- API --------------------------------------------------------------

    @property
    def docs(self) -> list[CorpusDoc]:
        return list(self._docs.values())

    def get(self, doc_id: str) -> CorpusDoc:
        return self._docs[doc_id]

    def doc_count(self) -> int:
        return len(self._docs)

    async def search(self, query: str, max_docs: int) -> list[SearchHit]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        total = len(self._index)
        scored: list[tuple[float, CorpusDoc, str]] = []
        for indexed in self._index.values():
            score = 0.0
            first_term: str | None = None
            for term in query_terms:
                tf = indexed.term_freq.get(term, 0)
                if tf == 0:
                    continue
                idf = math.log((total + 1) / (self._df.get(term, 0) + 1)) + 1.0
                score += tf * idf
                if first_term is None:
                    first_term = term
            if score <= 0.0:
                continue
            snippet = self._snippet(indexed.doc, first_term or "")
            scored.append((score, indexed.doc, snippet))
        scored.sort(key=lambda item: (-item[0], item[1].doc_id))
        return [
            SearchHit(doc_id=doc.doc_id, title=doc.title, score=round(score, 4), snippet=snippet)
            for score, doc, snippet in scored[: max(1, max_docs)]
        ]

    @staticmethod
    def _snippet(doc: CorpusDoc, term: str) -> str:
        for line in doc.text.splitlines():
            if term and term in line.lower():
                return line.strip()[:180]
        return doc.text[:180].strip()


class WebSearchBackend:
    """Optional HTTP search backend.

    Constructing it without an endpoint raises immediately, which keeps
    the guarded-import story honest: nothing here can silently fall back
    to network calls, and the offline test suite never instantiates it.
    """

    def __init__(self, endpoint: str, api_key: str = "", timeout_s: float = 20.0) -> None:
        if not endpoint:
            raise RuntimeError(
                "WebSearchBackend is disabled: set SWARM_WEB_SEARCH_ENDPOINT to enable it"
            )
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def search(self, query: str, max_docs: int) -> list[SearchHit]:
        response = await self._client.post(
            self.endpoint,
            json={"query": query, "max_docs": max_docs},
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
        )
        response.raise_for_status()
        return [SearchHit.model_validate(item) for item in response.json()["hits"]]


def select_backend(settings: SwarmSettings) -> SearchBackend:
    """Offline (or endpoint-less) configs always get the bundled corpus."""
    if settings.offline or not settings.web_search_endpoint:
        return BundledCorpusBackend(corpus_dir=settings.corpus_dir)
    return WebSearchBackend(
        endpoint=settings.web_search_endpoint, api_key=settings.llm_api_key
    )
