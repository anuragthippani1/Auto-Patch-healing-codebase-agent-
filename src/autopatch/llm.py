"""OpenRouter client, fix proposal, and JSON parsing of the model's reply."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from .config import redact, settings
from .models import Edit
from .prompts import RETRY_JSON_PROMPT, SYSTEM_PROMPT, build_user_prompt

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_FENCE = re.compile(r"^```[\w-]*[ \t]*\n(.*?)\n?```$", re.DOTALL)
_tokens_used = 0


class LLMError(Exception):
    """The model call failed or its reply could not be used."""


class FixProposal(BaseModel):
    """The JSON object the model must return."""

    reasoning: str = ""
    edits: list[Edit]


def tokens_used() -> int:
    """Total tokens reported by the API since this process started."""
    return _tokens_used


def strip_fences(text: str) -> str:
    """Remove a surrounding markdown code fence, if there is one."""
    text = text.strip()
    match = _FENCE.match(text)
    return match.group(1).strip() if match else text


def _load_json(text: str) -> object:
    """Parse JSON, tolerating a code fence or prose around the object."""
    cleaned = strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def parse_response(text: str) -> tuple[str, list[Edit]]:
    """Turn the model's reply into (reasoning, edits) or raise `LLMError`."""
    try:
        data = _load_json(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Reply was not valid JSON ({exc.msg}).") from exc
    try:
        proposal = FixProposal.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        )
        raise LLMError(f"Reply did not match the required schema ({problems}).") from exc
    if not proposal.edits:
        raise LLMError("Reply contained no edits.")
    return proposal.reasoning, proposal.edits


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """OpenAI SDK client pointed at OpenRouter."""
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=settings.openrouter_api_key.get_secret_value(),
        timeout=120,
    )


def _complete(messages: list[dict[str, str]]) -> str:
    """Send one chat completion and return the text of the reply."""
    global _tokens_used
    try:
        response = _client().chat.completions.create(
            model=settings.openrouter_model, messages=messages, temperature=0
        )
    except OpenAIError as exc:
        raise LLMError(f"LLM request failed ({type(exc).__name__}): {redact(str(exc))}") from exc
    if response.usage:
        _tokens_used += response.usage.total_tokens or 0
    if not response.choices:
        raise LLMError("LLM returned no choices.")
    return response.choices[0].message.content or ""


def propose_fix(
    issue_title: str,
    issue_body: str,
    source_files: dict[str, str],
    test_files: dict[str, str],
    test_log: str,
    previous_feedback: str = "",
) -> tuple[str, list[Edit]]:
    """Ask the model for a fix. Retries once if the reply is not usable JSON."""
    user_prompt = build_user_prompt(
        issue_title, issue_body, source_files, test_files, test_log, previous_feedback
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    reply = _complete(messages)
    try:
        return parse_response(reply)
    except LLMError as exc:
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": RETRY_JSON_PROMPT.format(error=exc)})
        return parse_response(_complete(messages))
