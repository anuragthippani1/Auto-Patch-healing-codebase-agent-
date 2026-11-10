"""Sandbox tests. They need a Docker daemon and the sandbox image."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopatch.config import settings
from autopatch.sandbox import SandboxError, run_pytest

pytestmark = pytest.mark.docker


def _repo(tmp_path: Path, test_body: str) -> str:
    """Create a one-test repo and return its path."""
    (tmp_path / "test_sample.py").write_text(test_body)
    return str(tmp_path)


def test_passing_repo(tmp_path: Path) -> None:
    result = run_pytest(_repo(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n"))
    assert result.passed is True
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "1 passed" in result.stdout


def test_failing_repo(tmp_path: Path) -> None:
    result = run_pytest(_repo(tmp_path, "def test_bad():\n    assert 1 + 1 == 3\n"))
    assert result.passed is False
    assert result.exit_code == 1
    assert result.timed_out is False
    assert "test_sample.py" in result.stdout


def test_infinite_loop_times_out(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "def test_forever():\n    while True:\n        pass\n")
    result = run_pytest(repo, timeout=5)
    assert result.timed_out is True
    assert result.passed is False
    assert result.exit_code == 124
    assert result.duration_s < 30


def test_network_is_unavailable(tmp_path: Path) -> None:
    body = (
        "import socket\n"
        "import pytest\n\n"
        "def test_no_network():\n"
        "    with pytest.raises(OSError):\n"
        "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
    )
    result = run_pytest(_repo(tmp_path, body))
    assert result.passed is True, result.stdout


def test_mount_is_read_only(tmp_path: Path) -> None:
    body = (
        "import pytest\n\n"
        "def test_cannot_write():\n"
        "    with pytest.raises(OSError):\n"
        "        open('/work/escaped.txt', 'w').write('x')\n"
    )
    result = run_pytest(_repo(tmp_path, body))
    assert result.passed is True, result.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == ["test_sample.py"]


def test_missing_image_has_clear_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sandbox_image", "autopatch-sandbox-does-not-exist:latest")
    with pytest.raises(SandboxError, match="autopatch build-sandbox"):
        run_pytest(_repo(tmp_path, "def test_ok():\n    pass\n"))
