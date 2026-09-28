"""Human-in-the-loop state machine (offline input sources)."""

from __future__ import annotations

import json

import pytest

from swarm.orchestra.human import (
    FileHumanInput,
    HumanInputQueue,
    HumanInterrupt,
    require_input,
)


def test_queue_returns_answers_in_order_then_raises():
    queue = HumanInputQueue(["first", "second"])
    assert queue.take() == "first"
    assert queue.take() == "second"
    with pytest.raises(LookupError):
        queue.take()


def test_require_input_pauses_when_empty():
    queue = HumanInputQueue([])
    with pytest.raises(HumanInterrupt) as excinfo:
        require_input(queue, "Approve X?", {"task": "x"})
    assert excinfo.value.prompt == "Approve X?"
    assert excinfo.value.payload == {"task": "x"}


def test_require_input_returns_queued_answer():
    assert require_input(HumanInputQueue(["yes"]), "Proceed?") == "yes"


def test_file_source_reads_json_array(tmp_path):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(["approve", "reject"]), encoding="utf-8")
    source = FileHumanInput(path)
    assert source.take() == "approve"
    assert source.take() == "reject"
    with pytest.raises(LookupError):
        source.take()


def test_file_source_rejects_non_array(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"answer": "yes"}), encoding="utf-8")
    with pytest.raises(ValueError):
        FileHumanInput(path).take()
