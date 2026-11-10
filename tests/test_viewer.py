"""Run listing (always tested) and a smoke test of the Streamlit page (if installed)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from autopatch.config import settings
from autopatch.logging_utils import list_runs, log_event, read_events, write_artifact


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two finished runs; 'newer' has the later event log."""
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path))
    for age, run_id, status in ((100, "older", "failed"), (0, "newer", "fixed")):
        log_event(run_id, "start", f"Run {run_id} (dry run): Cart total is wrong", {})
        log_event(run_id, "run_baseline_tests", "Baseline tests failed", {"log_tail": "1 failed"})
        end = {"status": status, "attempts": 2, "duration_s": 3.2, "pr_url": None}
        log_event(run_id, "end", f"Status: {status}", end)
        write_artifact(run_id, "report.md", f"# AutoPatch run {run_id}\n")
        stamp = (tmp_path / run_id / "events.jsonl").stat().st_mtime - age
        os.utime(tmp_path / run_id / "events.jsonl", (stamp, stamp))
    (tmp_path / "not-a-run").mkdir()
    return tmp_path


def test_list_runs_newest_first_and_skips_other_dirs(runs: Path) -> None:
    assert [path.name for path in list_runs()] == ["newer", "older"]
    assert list_runs(runs / "missing") == []


def test_events_are_json_lines_with_required_keys(runs: Path) -> None:
    events = read_events(runs / "newer")
    assert [event["node"] for event in events] == ["start", "run_baseline_tests", "end"]
    for line in (runs / "newer" / "events.jsonl").read_text().splitlines():
        assert set(json.loads(line)) == {"ts", "node", "summary", "data"}


def test_viewer_page_renders(runs: Path) -> None:
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    viewer = Path(__file__).resolve().parents[1] / "src" / "autopatch" / "viewer.py"
    page = AppTest.from_file(str(viewer), default_timeout=30).run()
    assert not page.exception
    assert page.title[0].value == "AutoPatch runs"
    assert [metric.value for metric in page.metric] == ["fixed", "2", "3.2 s"]
    assert any("run_baseline_tests" in expander.label for expander in page.expander)
