"""System and user prompt templates for the fix proposal."""

from __future__ import annotations

TEST_LOG_TAIL_CHARS = 6000

SYSTEM_PROMPT = """\
You are a careful senior Python engineer fixing a bug.
You are given a GitHub issue, failing pytest output, source files, and test files.
Rules:
- Fix the bug in SOURCE files only. NEVER modify test files.
- Make the smallest change that fixes the root cause. Do not refactor.
- Respond with ONLY a JSON object, no prose, no markdown fences:
  {"reasoning": "<1-3 sentences>", "edits": [{"path": "...", "search": "...", "replace": "..."}]}
- Each "search" must be copied EXACTLY from the file and appear exactly once. Include enough \
surrounding lines to make it unique.
- If previous feedback is provided, your last attempt failed; fix based on it.
"""

RETRY_JSON_PROMPT = (
    "Your previous reply could not be used: {error}\n"
    "Return valid JSON only, in exactly the format described, with at least one edit."
)


def _file_blocks(label: str, files: dict[str, str]) -> str:
    """Render files as labelled blocks."""
    blocks = (f"### {label}: {path}\n{content.rstrip()}\n" for path, content in files.items())
    return "\n".join(blocks)


def build_user_prompt(
    issue_title: str,
    issue_body: str,
    source_files: dict[str, str],
    test_files: dict[str, str],
    test_log: str,
    previous_feedback: str = "",
) -> str:
    """Assemble the user message for one fix attempt."""
    parts = [
        f"## GitHub issue\nTitle: {issue_title}\n\n{issue_body.strip()}",
        f"## Failing pytest output\n{test_log[-TEST_LOG_TAIL_CHARS:].strip()}",
        "## Source files (you may edit these)\n" + _file_blocks("FILE", source_files),
    ]
    if test_files:
        parts.append(
            "## Test files (do not edit)\n" + _file_blocks("TEST FILE (read-only)", test_files)
        )
    if previous_feedback:
        parts.append(
            "## Previous feedback\nYour last attempt failed. The files above are the ORIGINAL, "
            f"unpatched versions; write edits against them.\n{previous_feedback.strip()}"
        )
    return "\n\n".join(parts)
