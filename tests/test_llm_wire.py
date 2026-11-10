"""What the real OpenAI SDK client sends, checked against a local HTTP server (no internet)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import SecretStr

from autopatch import llm
from autopatch.config import settings

REPLY = {"reasoning": "Wrong operator.", "edits": [{"path": "a.py", "search": "-", "replace": "+"}]}


class _FakeOpenRouter(BaseHTTPRequestHandler):
    """Records each request and answers like an OpenAI-compatible chat endpoint."""

    requests: list[dict] = []
    status = 200

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": body}
        )
        if self.status == 200:
            message = {"role": "assistant", "content": json.dumps(REPLY)}
            payload = {
                "id": "gen-1", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 23, "total_tokens": 123},
            }
        else:
            payload = {"error": {"message": "User not found.", "code": self.status}}
        data = json.dumps(payload).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        """Keep test output quiet."""


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeOpenRouter]]:
    """Point the real client at a local server for one test."""
    _FakeOpenRouter.requests, _FakeOpenRouter.status = [], 200
    httpd = HTTPServer(("127.0.0.1", 0), _FakeOpenRouter)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(llm, "OPENROUTER_BASE_URL", f"http://127.0.0.1:{httpd.server_port}/api/v1")
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("sk-or-test-key"))
    monkeypatch.setattr(settings, "openrouter_model", "anthropic/claude-sonnet-4.5")
    llm._client.cache_clear()
    yield _FakeOpenRouter
    llm._client.cache_clear()
    httpd.shutdown()
    httpd.server_close()


def test_request_carries_key_model_and_temperature(server: type[_FakeOpenRouter]) -> None:
    before = llm.tokens_used()
    reasoning, edits = llm.propose_fix("Title", "Body", {"a.py": "x = 1 - 1\n"}, {}, "1 failed")

    assert reasoning == "Wrong operator." and edits[0].path == "a.py"
    assert llm.tokens_used() == before + 123
    (request,) = server.requests
    assert request["path"] == "/api/v1/chat/completions"
    assert request["auth"] == "Bearer sk-or-test-key"
    assert request["body"]["model"] == "anthropic/claude-sonnet-4.5"
    assert request["body"]["temperature"] == 0
    assert request["body"]["max_tokens"] == 2048
    assert [message["role"] for message in request["body"]["messages"]] == ["system", "user"]


def test_rejected_key_becomes_llm_error_without_leaking_it(server: type[_FakeOpenRouter]) -> None:
    server.status = 401
    with pytest.raises(llm.LLMError, match="AuthenticationError") as excinfo:
        llm.propose_fix("Title", "Body", {"a.py": "x"}, {}, "log")
    assert "sk-or-test-key" not in str(excinfo.value)
    assert len(server.requests) == 1
