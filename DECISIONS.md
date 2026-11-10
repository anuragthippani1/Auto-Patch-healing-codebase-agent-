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

## M5: LangGraph loop

- **Each attempt starts from the original code.** `git checkout -- .` runs first, then the
  new edit set replaces the old one (the spec's "simplest" option). Because the LLM is then
  shown the unpatched files, the feedback for a retry includes the edits it proposed last
  time plus what happened (edit error, or the tail of the failing test log).
- **`baseline_log` is kept separately from `test_log`.** The prompt's "failing pytest
  output" is always the log of the unpatched repo, which matches the files shown. The log
  of the failed patch goes into the feedback section. Files are picked from both logs.
- **An extra conditional edge after `propose_and_apply`** (`route_after_apply`). The spec
  says an `EditError` must skip the test run; this edge does that. LLM errors (bad JSON
  twice, API failure) take the same path and also count as an attempt.
- **Baseline exit code 5 (pytest collected no tests) goes straight to `give_up`.** Without
  tests no fix can be verified, so calling the LLM three times would only cost money.
- **`run_agent` never raises.** Any exception inside the graph (Docker down, clone failed,
  push rejected) ends the run with `status="failed"`, the error in `last_error`, and a
  `report.md`. The graph is consumed with `stream(..., stream_mode="values")` so the state
  reached before the crash is kept.
- **`fix.patch` is written on every fixed run**, not only dry runs, so the fix survives
  even if the push or the PR call fails afterwards. `last_attempt.patch` holds the last
  diff that was actually applied; it is not written if no edit was ever applied.
- **The working copy is deleted at the end of every run.** Local paths are copied first,
  so the user's directory is never modified (and never gets a `.git` added).
- **Local repos with uncommitted changes:** the copy commits everything as "AutoPatch
  baseline snapshot", so `git checkout -- .` restores the user's current state, bug included.
- **CLI argument rules.** A real run needs a GitHub URL and `--issue`. A local path needs
  `--issue-file` and `--dry-run`. A GitHub URL with `--issue` and `--dry-run` is allowed
  (fetches the issue, opens no PR). Usage and config errors exit with code 1, keeping
  exit code 2 for `no_repro`.
- **`autopatch eval` forwards extra options** to `eval/run_eval.py` (`--only`, `--check`).
- **`run_eval.py --check`** (not in the spec) verifies, with no LLM call, that the clean repo
  passes and each patch makes the tests fail. It was needed to validate the bug set
  without an API key, and is useful when adding bugs.
- **Evidence for M5 without an API key:** `tests/test_e2e_dry_run.py` runs the real CLI
  with the real Docker sandbox on eval bug 09 and a scripted model reply (first reply
  incomplete, second correct). The acceptance command with a real model has NOT been run.
