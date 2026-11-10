# Decisions

Choices made where the spec was ambiguous, and anything added beyond it.

## M1: Skeleton

- **Repo root is the workspace folder.** The spec's `autopatch/` root maps to this directory.
- **Build backend: hatchling**, with a `src/` layout. Dev tools (`pytest`, `ruff`) live in the
  `dev` extra and `streamlit` in the `viewer` extra, so the core install stays small.
- **Secrets are `SecretStr`.** `OPENROUTER_API_KEY` and `GITHUB_TOKEN` are wrapped so they
  cannot leak through a `repr`, a log line, or a traceback.
- **Two extra settings:** `RUNS_DIR` (default `runs`) and `WORK_DIR` (default: system temp).
  `WORK_DIR` exists for docker-compose, where the working copy must sit at a path that is
  the same on the host and in the container (see M8).
- **Extra `State` fields.** The spec's `State` has no issue number, but the PR branch name
  and `Fixes #N` need one, so `issue_number` was added. Also added: `max_attempts` (so
  `route_after_tests` is pure and does not read global settings), `baseline_log`,
  `baseline_exit_code`, `apply_ok`, `reasoning`, `diff`, `history`, `tokens`, `started_at`,
  `duration_s`. Each is explained where it is used below.

## M2: Sandbox

- **`containers.create` + `start` instead of `containers.run`.** `run` silently tries to
  pull a missing image from a registry. `create` fails at once with `ImageNotFound`, which
  becomes a `SandboxError` telling the user to run `autopatch build-sandbox`.
- **Only timeouts count as `timed_out`.** The spec's sketch catches every `Exception` in
  `container.wait`. Only `ReadTimeout` / `ConnectionError` are caught here, so a real Docker
  API failure surfaces as an error and is not misreported as a slow test.
- **A timeout appends a line to the log** (`[autopatch] Test run timed out ...`), so the LLM
  feedback explains why there is no pytest summary.
- **`build-sandbox` sends only the Dockerfile**, not the repo as build context. The
  Dockerfile copies nothing, and this avoids uploading `.venv/` to the daemon.
- **`AUTOPATCH_REQUIRE_DOCKER=1`** turns "docker tests skipped" into a hard error. CI sets
  it in the docker job so a broken image build cannot produce a green run with zero tests.
- **Extra sandbox tests:** the read-only mount and the missing-image message are tested in
  addition to the four cases the spec lists.

## M3: Edits and localization

- **More paths are protected than the spec lists.** Besides `tests/`, `test_*.py` and
  `*_test.py`, edits are rejected for `conftest.py`, a `test/` directory, anything under
  `.git/`, and every non-`.py` file. Reason: an LLM could otherwise make the suite "pass"
  by changing `conftest.py`, `pytest.ini`, `pyproject.toml` or `setup.cfg` rather than
  fixing the bug. Matching is case-insensitive and is also applied to the resolved path,
  so a symlink to a test file is rejected too.
- **Empty and no-op edits are errors** (empty `search`, `search == replace`, empty edit
  list). They would otherwise spend a sandbox run on an unchanged repo.
- **Reverting uses git, not snapshots.** `git checkout -- .` before each attempt (the
  spec's "simplest" option). Edits can only modify existing tracked `.py` files and the
  sandbox mount is read-only, so there is never an untracked file to clean up.
- **`select_context` returns a `Context` dataclass** (`source_files`, `test_files`), not one
  dict, because the spec also asks for sources and tests to be returned separately.
- **Context order:** files in the order they appear in the log, then modules imported by
  the failing test files. A file that would exceed `max_chars` is skipped and smaller
  later files may still be added, so the total never exceeds the budget.
- **Fallback triggers when no *source* file was found**, even if a test file was. A log
  that only names the test file still needs source code in the prompt.

## M4: LLM layer

- **`propose_fix` returns `(reasoning, edits)`**, as the parsing paragraph of the spec says
  (the signature line says `list[Edit]`; the PR body needs the reasoning).
- **Parsing tolerates prose around the JSON object** as well as code fences: if the reply
  does not parse, the text from the first `{` to the last `}` is tried before giving up.
- **A reply with zero edits is an `LLMError`**, the same as invalid JSON, so it triggers the
  one "Return valid JSON only" retry.
- **API failures become `LLMError`** with the API key redacted from the message. The agent
  then records a failed attempt and still writes a report, rather than crashing.
- **Token counting** is a module-level counter in `llm.py` (`tokens_used()`), fed from the
  `usage` field of each response. Cost is not computed; OpenRouter prices vary per model.
- **The M4 "manual smoke test against a real call" has NOT been run**: no
  `OPENROUTER_API_KEY` was available in the build environment. Only mocked tests cover
  `llm.py`.
