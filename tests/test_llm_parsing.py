"""Tests for the LLM layer. The API is always mocked; nothing touches the network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from autopatch import llm
from autopatch.llm import LLMError, parse_response, propose_fix
from autopatch.models import Edit
from autopatch.prompts import SYSTEM_PROMPT, build_user_prompt

GOOD = {
    "reasoning": "The operator was wrong.",
    "edits": [{"path": "calc.py", "search": "a - b", "replace": "a + b"}],
}
GOOD_JSON = json.dumps(GOOD)


def _fake_complete(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[list[dict]]:
    """Replace the API call with scripted replies; return the recorded message lists."""
    calls: list[list[dict]] = []

    def fake(messages: list[dict]) -> str:
        calls.append([dict(m) for m in messages])
        return replies[len(calls) - 1]

    monkeypatch.setattr(llm, "_complete", fake)
    return calls


def _propose() -> tuple[str, list[Edit]]:
    return propose_fix("Title", "Body", {"calc.py": "x"}, {"tests/test_calc.py": "y"}, "log")


def test_parses_clean_json() -> None:
    reasoning, edits = parse_response(GOOD_JSON)
    assert reasoning == "The operator was wrong."
    assert edits == [Edit(path="calc.py", search="a - b", replace="a + b")]


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```", "  ```JSON\n{}\n```  \n"])
def test_strips_code_fences(fence: str) -> None:
    _, edits = parse_response(fence.replace("{}", GOOD_JSON))
    assert edits[0].path == "calc.py"


def test_tolerates_prose_around_json() -> None:
    _, edits = parse_response(f"Here is the fix:\n{GOOD_JSON}\nHope that helps!")
    assert edits[0].replace == "a + b"


@pytest.mark.parametrize(
    "bad",
    [
        {"reasoning": "x"},
        {"reasoning": "x", "edits": "not a list"},
        {"reasoning": "x", "edits": [{"path": "calc.py", "search": "a"}]},
        {"reasoning": "x", "edits": [{"path": 1, "search": "a", "replace": "b"}]},
        ["not", "an", "object"],
    ],
)
def test_rejects_bad_schema(bad: object) -> None:
    with pytest.raises(LLMError, match="schema"):
        parse_response(json.dumps(bad))


def test_rejects_empty_edit_list() -> None:
    with pytest.raises(LLMError, match="no edits"):
        parse_response(json.dumps({"reasoning": "nothing to do", "edits": []}))


@pytest.mark.parametrize("bad", ["", "I could not find the bug.", "{not json}"])
def test_rejects_invalid_json(bad: str) -> None:
    with pytest.raises(LLMError, match="not valid JSON"):
        parse_response(bad)


def test_propose_fix_returns_reasoning_and_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_complete(monkeypatch, [GOOD_JSON])
    reasoning, edits = _propose()
    assert reasoning == "The operator was wrong."
    assert len(edits) == 1
    assert len(calls) == 1
    assert calls[0][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_propose_fix_retries_once_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_complete(monkeypatch, ["Sorry, here you go", GOOD_JSON])
    _, edits = _propose()
    assert edits[0].path == "calc.py"
    assert len(calls) == 2
    assert calls[1][-2] == {"role": "assistant", "content": "Sorry, here you go"}
    assert "Return valid JSON only" in calls[1][-1]["content"]


def test_propose_fix_gives_up_after_one_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_complete(monkeypatch, ["nope", "still nope", GOOD_JSON])
    with pytest.raises(LLMError):
        _propose()
    assert len(calls) == 2


def test_user_prompt_labels_files_and_truncates_log() -> None:
    log = "OLD" + "x" * 7000 + "LOG_END"
    prompt = build_user_prompt(
        "Cart total wrong", "Totals are off.", {"shop/cart.py": "SRC"},
        {"tests/test_cart.py": "TEST"}, log, previous_feedback="FEEDBACK_TEXT",
    )
    assert "Title: Cart total wrong" in prompt and "Totals are off." in prompt
    assert "### FILE: shop/cart.py\nSRC" in prompt
    assert "### TEST FILE (read-only): tests/test_cart.py\nTEST" in prompt
    assert "LOG_END" in prompt and "OLD" not in prompt
    assert "FEEDBACK_TEXT" in prompt


def test_user_prompt_omits_feedback_section_on_first_attempt() -> None:
    prompt = build_user_prompt("T", "B", {"a.py": "SRC"}, {}, "log")
    assert "Previous feedback" not in prompt


def test_complete_uses_model_and_temperature_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def create(**kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        message = SimpleNamespace(content="reply text")
        usage = SimpleNamespace(total_tokens=42)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_client", lambda: fake_client)
    before = llm.tokens_used()
    assert llm._complete([{"role": "user", "content": "hi"}]) == "reply text"
    assert seen["temperature"] == 0
    assert seen["max_tokens"] == llm.settings.max_output_tokens
    assert seen["model"] == llm.settings.openrouter_model
    assert llm.tokens_used() == before + 42
