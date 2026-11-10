"""Streamlit viewer for AutoPatch runs.

    pip install -e ".[viewer]"
    streamlit run src/autopatch/viewer.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from autopatch.config import settings
from autopatch.logging_utils import list_runs, read_events


def _final(events: list[dict]) -> dict:
    """Data of the 'end' event, or an empty dict if the run did not finish."""
    return next((e["data"] for e in reversed(events) if e["node"] == "end"), {})


def _label(run_path: Path) -> str:
    """Sidebar label: status, run id, and issue title."""
    events = read_events(run_path)
    status = _final(events).get("status", "unfinished")
    title = events[0]["summary"].split(": ", 1)[-1] if events else ""
    return f"[{status}] {run_path.name}  {title[:40]}"


def _show_summary(events: list[dict]) -> None:
    """Status, attempts, duration and PR link across the top."""
    final = _final(events)
    status, attempts, duration = st.columns(3)
    status.metric("Status", final.get("status", "unfinished"))
    attempts.metric("Attempts", final.get("attempts", "-"))
    duration.metric("Duration", f"{final['duration_s']:.1f} s" if final else "-")
    if final.get("pr_url"):
        st.markdown(f"**Pull request:** {final['pr_url']}")


def _show_timeline(events: list[dict]) -> None:
    """One expander per event, in order."""
    st.subheader("Step timeline")
    for index, event in enumerate(events, start=1):
        time = event["ts"][11:19]
        with st.expander(f"{index}. {time}  {event['node']}: {event['summary']}"):
            data = dict(event["data"])
            log_tail = data.pop("log_tail", "")
            if log_tail:
                st.code(log_tail, language="text")
            if data:
                st.json(data)


def _show_files(run_path: Path) -> None:
    """The report and any saved patch."""
    report = run_path / "report.md"
    for name in ("fix.patch", "last_attempt.patch"):
        if (run_path / name).is_file():
            st.subheader(name)
            st.code((run_path / name).read_text(encoding="utf-8"), language="diff")
    if report.is_file():
        st.subheader("Report")
        st.markdown(report.read_text(encoding="utf-8"))


def main() -> None:
    """Render the page."""
    st.set_page_config(page_title="AutoPatch runs", layout="wide")
    st.title("AutoPatch runs")
    runs = list_runs()
    if not runs:
        st.info(f"No runs found in '{settings.runs_dir}/'. Run `autopatch fix ...` first.")
        return
    run_path = st.sidebar.selectbox("Run", runs, format_func=_label)
    events = read_events(run_path)
    _show_summary(events)
    _show_timeline(events)
    _show_files(run_path)


main()
