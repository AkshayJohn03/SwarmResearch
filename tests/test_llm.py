"""LLM client layer: Protocol surface, Echo determinism, OpenAI payload shape."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from swarm.llm import EchoMockClient, LLMClient, Message, OpenAICompatClient


def test_echo_client_is_deterministic_and_protocol_compliant():
    client = EchoMockClient()
    assert isinstance(client, LLMClient)
    messages = [Message(role="user", content="hello world")]
    first = asyncio.run(client.complete(messages))
    second = asyncio.run(client.complete(messages))
    assert first == second
    assert first.startswith("[echo:")
    assert "hello world" in first
    assert client.calls == 2


def test_echo_stream_yields_whole_text_in_chunks():
    client = EchoMockClient()
    chunks = asyncio.run(_collect(client))
    assert "".join(chunks) == asyncio.run(client.complete([Message(role="user", content="abc")]))


async def _collect(client) -> list[str]:
    return [chunk async for chunk in client.stream([Message(role="user", content="abc")])]


def test_openai_client_payload_and_parsing():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "the answer"}}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatClient(
        base_url="https://example.test/v1",
        api_key="k-test",
        model="test-model",
        client=httpx.AsyncClient(transport=transport),
    )
    answer = asyncio.run(
        client.complete([Message(role="user", content="q")], temperature=0.1, max_tokens=64)
    )
    assert answer == "the answer"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer k-test"
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["max_tokens"] == 64


def test_web_search_backend_is_guarded_without_endpoint():
    from swarm.agents.search import WebSearchBackend

    with pytest.raises(RuntimeError, match="SWARM_WEB_SEARCH_ENDPOINT"):
        WebSearchBackend(endpoint="")
