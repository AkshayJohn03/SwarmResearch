"""LLM access layer.

Every consumer depends on the :class:`LLMClient` Protocol, never on a
vendor SDK.  Two implementations ship:

* :class:`OpenAICompatClient` -- any OpenAI-compatible ``/chat/completions``
  endpoint (complete + SSE streaming), used only when offline mode is off.
* :class:`EchoMockClient` -- deterministic, offline; useful for tests and
  for plumbing the pipeline end-to-end without keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from swarm.settings import SwarmSettings


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@runtime_checkable
class LLMClient(Protocol):
    """The only LLM surface the rest of the codebase is allowed to see."""

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str: ...

    def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...


class OpenAICompatClient:
    """Minimal OpenAI-compatible client over httpx (no vendor SDK)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    @classmethod
    def from_settings(cls, settings: SwarmSettings) -> OpenAICompatClient:
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_s=settings.request_timeout_s,
        )

    def _payload(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None, stream: bool
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            json=self._payload(messages, temperature, max_tokens, stream=False),
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=self._payload(messages, temperature, max_tokens, stream=True),
            headers=self._headers(),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[len("data: "):]
                if chunk.strip() == "[DONE]":
                    break
                delta = json.loads(chunk)["choices"][0].get("delta", {})
                piece = delta.get("content")
                if piece:
                    yield piece

    async def aclose(self) -> None:
        await self._client.aclose()


class EchoMockClient:
    """Deterministic offline client.

    Never calls the network; output is a pure function of the input so
    tests are reproducible.  Tracks ``calls`` so tests can assert that the
    offline pipeline does (or does not) touch the LLM.
    """

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _digest(messages: Sequence[Message]) -> str:
        content = messages[-1].content if messages else ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        content = messages[-1].content if messages else ""
        return f"[echo:{self._digest(messages)}] {content[:240]}"

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        text = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        for i in range(0, len(text), 48):
            yield text[i : i + 48]
            await asyncio.sleep(0)
