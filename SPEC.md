# AutoPatch: Self-Healing Codebase Agent (Build Spec for Cursor)

> **Cursor: read this whole file first, then build milestone by milestone (Section 12).**
> After every milestone: run the tests, fix failures, and commit. Do not ask me questions. If something is ambiguous, pick the simplest option and note it in `DECISIONS.md`.

---

## 1. What we are building

AutoPatch is an agent that takes a GitHub issue describing a bug in a Python repo, then:

1. Clones the repo
2. Reproduces the failure by running `pytest` inside a locked-down Docker sandbox
3. Asks an LLM to locate the bug and write a fix
4. Applies the fix and re-runs the tests in the sandbox
5. Retries up to 3 times, feeding back the new test log
6. If tests pass, pushes a branch and opens a Pull Request with an explanation and test results
7. If it cannot fix the bug, stops with a clear `failed` status and a report

**Scope (MVP):** Python repos only, pytest tests, stdlib-only dependencies (see 6.1), single user, CLI first, optional Streamlit viewer at the end.

**Non-goals:** auth, multi-tenancy, queues, databases, Kubernetes, multi-language support, fancy UI.

**Hard safety rules (never violate):**
- Never push to the default branch (`main`/`master`). Only create `autopatch/*` branches and open PRs.
- Never edit files under `tests/` or any `test_*.py` / `*_test.py` file. The agent fixes source code, not tests.
- All test execution happens in Docker with no network. Never run repo code on the host.
- Never log or commit secrets. Keys come from `.env` only.

---

## 2. Tech stack

- Python 3.11+
- `langgraph` (agent flow)
- `docker` (Docker SDK for Python, for the sandbox)
- `PyGithub` (issues, PRs) plus plain `git` via `subprocess` (clone, branch, commit, push)
- `openai` SDK pointed at OpenRouter (`base_url="https://openrouter.ai/api/v1"`)
- `pydantic` + `pydantic-settings` (config, typed models)
- `typer` + `rich` (CLI and readable logs)
- `pytest` (our own tests)
- Optional: `streamlit` (run viewer)
- Packaging: `Dockerfile.sandbox`, `docker-compose.yml`, GitHub Actions CI

---

## 3. Repository layout

```
autopatch/
├─ SPEC.md
├─ DECISIONS.md
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ .gitignore
├─ docker/
│  └─ Dockerfile.sandbox
├─ docker-compose.yml
├─ src/autopatch/
│  ├─ __init__.py
│  ├─ config.py            # Settings from env
│  ├─ models.py            # Pydantic models: Edit, SandboxResult, RunReport
│  ├─ cli.py               # Typer CLI
│  ├─ graph.py             # LangGraph definition
│  ├─ nodes.py             # Node functions
│  ├─ sandbox.py           # Docker pytest runner
│  ├─ llm.py               # OpenRouter client + prompt + JSON parsing
│  ├─ localize.py          # Pick relevant files from a test log
│  ├─ edits.py             # Safe edit application
│  ├─ github_ops.py        # Fetch issue, branch, push, open PR
│  ├─ logging_utils.py     # JSONL event log + report.md writer
│  └─ prompts.py           # System and user prompt templates
├─ eval/
│  ├─ clean_repo/          # Small clean Python project with passing tests
│  ├─ bugs/                # 10 bug definitions (NN.patch + NN.md issue text)
│  └─ run_eval.py          # Runs the agent on all 10, prints results table
├─ tests/                  # Our own tests for AutoPatch
│  ├─ test_edits.py
│  ├─ test_localize.py
│  ├─ test_llm_parsing.py
│  ├─ test_sandbox.py      # marked @pytest.mark.docker
│  └─ test_graph_routing.py
├─ runs/                   # Generated run reports (gitignored)
└─ .github/workflows/ci.yml
```

---

## 4. Configuration (`config.py`, `.env.example`)

`.env.example`:
```
OPENROUTER_API_KEY=
OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
GITHUB_TOKEN=
SANDBOX_IMAGE=autopatch-sandbox:latest
SANDBOX_TIMEOUT_SECONDS=60
SANDBOX_MEMORY=512m
MAX_ATTEMPTS=3
MAX_CONTEXT_CHARS=30000
```

Use `pydantic-settings` with `.env` loading. Fail fast with a clear message if a required key is missing for the chosen mode (`--dry-run` does not need `GITHUB_TOKEN`).

---

## 5. Data models (`models.py`)

```python
class Edit(BaseModel):
    path: str          # relative to repo root
    search: str        # exact text to find (must occur exactly once)
    replace: str       # replacement text

class SandboxResult(BaseModel):
    exit_code: int
    stdout: str
    timed_out: bool
    passed: bool       # exit_code == 0 and not timed_out
    duration_s: float

class State(TypedDict):   # LangGraph state
    issue_title: str
    issue_body: str
    repo_url: str          # URL or local path
    repo_path: str         # working copy on host
    default_branch: str
    test_log: str
    baseline_failed: bool  # True if tests failed before patching
    edits: list[dict]      # all edits applied so far (cumulative)
    last_error: str        # edit error or test log feedback for next attempt
    attempts: int
    status: str            # running | fixed | failed | no_repro
    pr_url: str | None
    dry_run: bool
    run_id: str
```

---

## 6. Components

### 6.1 Sandbox (`sandbox.py`, `docker/Dockerfile.sandbox`)

`docker/Dockerfile.sandbox`:
```dockerfile
FROM python:3.11-slim
RUN pip install --no-cache-dir pytest
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
```

Build with: `docker build -f docker/Dockerfile.sandbox -t autopatch-sandbox:latest .`

**Limitation (document in README):** because the sandbox has no network, target repos must only need the standard library plus pytest. Mention "dependency install phase" as future work.

`run_pytest(repo_path: str, timeout: int) -> SandboxResult`:

```python
import time, docker
from .config import settings
from .models import SandboxResult

def run_pytest(repo_path: str, timeout: int | None = None) -> SandboxResult:
    timeout = timeout or settings.sandbox_timeout_seconds
    client = docker.from_env()
    start = time.time()
    container = client.containers.run(
        settings.sandbox_image,
        ["python", "-m", "pytest", "-x", "-q", "--tb=short", "-p", "no:cacheprovider"],
        working_dir="/work",
        volumes={repo_path: {"bind": "/work", "mode": "ro"}},  # read-only mount
        network_mode="none",
        mem_limit=settings.sandbox_memory,
        nano_cpus=1_000_000_000,
        pids_limit=128,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        detach=True,
    )
    timed_out = False
    try:
        try:
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", 1)
        except Exception:      # timeout or connection error
            timed_out = True
            exit_code = 124
            container.kill()
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
    finally:
        container.remove(force=True)
    return SandboxResult(
        exit_code=exit_code, stdout=logs[-8000:], timed_out=timed_out,
        passed=(exit_code == 0 and not timed_out), duration_s=time.time() - start,
    )
```

Notes: mount read-only so repo code cannot modify the host copy; truncate logs to the last 8000 chars; handle `docker.errors.ImageNotFound` with a clear message telling the user to build the image.

### 6.2 Localization (`localize.py`)

`select_context(repo_path, test_log, max_chars) -> dict[str, str]` returns `{relative_path: file_content}`.

Algorithm:
1. Regex the test log for paths like `src/foo.py:12` or `foo.py:12` and for `File "...py"` patterns. Collect unique `.py` paths that exist in the repo.
2. Include the failing test file(s) as read-only context (marked as tests).
3. For each failing test file, parse `import` / `from X import` lines and include matching local modules.
4. If nothing was found, fall back to all `.py` files outside `tests/`, smallest first.
5. Stop adding files once the total reaches `max_chars`. Never include `.git`, `venv`, `node_modules`, or files over 20 KB.

Return source files and test files separately so the prompt can label tests as "do not edit".

### 6.3 Edits (`edits.py`)

`apply_edits(repo_path, edits: list[Edit]) -> None`. Raises `EditError` with a helpful message for the retry loop.

Rules:
- Resolve each path with `Path(repo_path, e.path).resolve()` and reject anything outside `repo_path` (path traversal).
- Reject any path that matches `tests/` or `test_*.py` or `*_test.py`.
- Reject if the file does not exist.
- `search` must occur **exactly once**. If 0 or more than 1, raise `EditError` stating which and show the nearest similar lines if easy.
- Apply all edits atomically: validate all first, then write. If one fails, write none.

Also implement `snapshot(repo_path)` and `restore(repo_path, snapshot)` (or use `git stash` / `git checkout .`) so a failed attempt can be reverted before the next try. Simplest: before each attempt, run `git checkout -- .` in the working copy, then re-apply the new cumulative edit set.

### 6.4 LLM (`llm.py`, `prompts.py`)

Client:
```python
from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=settings.openrouter_api_key)
```

`propose_fix(issue_title, issue_body, source_files, test_files, test_log, previous_feedback) -> list[Edit]`

System prompt (put in `prompts.py`):
```
You are a careful senior Python engineer fixing a bug.
You are given a GitHub issue, failing pytest output, source files, and test files.
Rules:
- Fix the bug in SOURCE files only. NEVER modify test files.
- Make the smallest change that fixes the root cause. Do not refactor.
- Respond with ONLY a JSON object, no prose, no markdown fences:
  {"reasoning": "<1-3 sentences>", "edits": [{"path": "...", "search": "...", "replace": "..."}]}
- Each "search" must be copied EXACTLY from the file and appear exactly once. Include enough surrounding lines to make it unique.
- If previous feedback is provided, your last attempt failed; fix based on it.
```

User prompt template includes: issue title/body, test log (last 6000 chars), each source file as `### FILE: path` blocks, each test file as `### TEST FILE (read-only): path`, and previous feedback if any.

Parsing: strip code fences if present, `json.loads`, validate with pydantic. On invalid JSON, retry once with "Return valid JSON only". Return `(reasoning, edits)`. Use `temperature=0`.

### 6.5 GitHub ops (`github_ops.py`)

- `fetch_issue(repo_full_name, number) -> (title, body)` via PyGithub.
- `clone(repo_url_or_path) -> (repo_path, default_branch)`: if it is a local path, copy it to a temp dir and `git init` + commit if it is not a git repo; if it is a GitHub URL, `git clone` using the token (`https://x-access-token:{token}@github.com/owner/repo.git`), then detect the default branch.
- `open_pr(state) -> pr_url`:
  1. `branch = f"autopatch/issue-{number}-{run_id[:6]}"`
  2. **Guard:** `assert branch != default_branch`
  3. `git checkout -b branch`, `git add -A`, `git commit -m "fix: <issue title> (AutoPatch)"`
  4. `git push origin branch`
  5. Create PR into `default_branch` via PyGithub with title `[AutoPatch] <issue title>`
  6. PR body contains: `Fixes #<number>`, the LLM `reasoning`, files changed, number of attempts, the final passing test output (last 20 lines), and a note: "Generated by AutoPatch. Please review before merging."

### 6.6 Logging (`logging_utils.py`)

- Every node appends a JSON line to `runs/<run_id>/events.jsonl`: `{ts, node, summary, data}`.
- At the end write `runs/<run_id>/report.md` with: issue, status, attempts, each attempt's reasoning, edits, test result, total duration, PR link.
- Use `rich` to print a live step-by-step trace in the CLI.

---

## 7. LangGraph flow (`graph.py`, `nodes.py`)

```
START
  → clone_repo
  → run_baseline_tests
        ├─ passed ──────────────→ no_repro → END      (status "no_repro": tests already pass)
        └─ failed
  → propose_and_apply   (LLM → edits → apply)
  → run_tests_after
        ├─ passed ──────────────→ open_pr (or skip if dry_run) → END   (status "fixed")
        ├─ failed, attempts < MAX → propose_and_apply   (loop; feedback = new test log or edit error)
        └─ failed, attempts >= MAX → give_up → END      (status "failed")
```

Node behaviour:

- `clone_repo`: sets `repo_path`, `default_branch`.
- `run_baseline_tests`: runs `run_pytest`; stores `test_log`; sets `baseline_failed`. If it passed, route to `no_repro`.
- `propose_and_apply`: `git checkout -- .` to reset, call `select_context` and `propose_fix`, merge any new edits with prior successful context if needed (simplest: replace edits with the new set each attempt), call `apply_edits`. If `EditError`, set `last_error` and increment `attempts` without running tests (so the next loop gets the error as feedback).
- `run_tests_after`: runs the sandbox; sets `test_log`, `last_error` (test log tail), `status="fixed"` if passed.
- `open_pr`: if `dry_run`, skip the push and just write the diff to `runs/<id>/fix.patch`; otherwise call `github_ops.open_pr`.
- `give_up`: `status="failed"`, saves the last attempted diff to `runs/<id>/last_attempt.patch`.

`route_after_tests(state) -> "open_pr" | "retry" | "give_up"` must be a pure function so it can be unit tested.

---

## 8. CLI (`cli.py`)

```
autopatch fix --repo <github_url_or_local_path> --issue <number>          # real run, opens PR
autopatch fix --repo <path> --issue-file issue.md --dry-run               # local, no GitHub needed
autopatch eval                                                            # runs eval/run_eval.py
autopatch build-sandbox                                                   # builds the Docker image
```

- `--issue-file` format: first line is the title, the rest is the body.
- Exit code 0 if fixed, 1 if failed, 2 if no_repro.
- Print a final summary table: status, attempts, duration, PR URL or patch path.

---

## 9. Evaluation (`eval/`), the part that makes this project stand out

**`eval/clean_repo/`**: a small Python package (about 10 modules such as `strings.py`, `mathutils.py`, `dates.py`, `inventory.py`, `parser.py`, `cart.py`, `stack.py`, `cache.py`, `validators.py`, `pagination.py`) with a `tests/` folder where **all tests pass**.

**`eval/bugs/`**: 10 bugs, each as `NN.patch` (a unified diff that injects the bug into the clean repo) and `NN.md` (a realistic issue: title + description of symptoms, no hint of the exact line). Mix of difficulty:
- Easy (4): off-by-one, wrong operator, wrong comparison (`<` vs `<=`), swapped arguments
- Medium (4): wrong default argument, mutable default bug, missing edge-case handling (empty list/None), wrong string formatting
- Hard (2): bug spanning two functions, incorrect algorithm logic (e.g. wrong pagination math)

**`eval/run_eval.py`** for each bug:
1. Copy `clean_repo` to a temp dir, `git init`, commit, apply `NN.patch`, commit.
2. Confirm baseline tests fail (otherwise skip the bug and flag it).
3. Run the agent in `--dry-run` mode with `NN.md` as the issue.
4. Record: fixed (yes/no), attempts, duration, and tokens/cost if available.

Print and save a results table to `eval/results.md`:

| Bug | Difficulty | Fixed | Attempts | Time (s) |
|---|---|---|---|---|

Plus the summary line: **"Fixed X/10 (Y%), avg attempts Z, avg time W s"**. Put this table in the README.

---

## 10. Tests for AutoPatch itself (`tests/`)

- `test_edits.py`: applies a valid edit; rejects path traversal; rejects test-file edits; rejects non-unique `search`; atomicity (one bad edit means no change).
- `test_localize.py`: extracts file paths from a sample pytest log; respects `max_chars`; falls back correctly.
- `test_llm_parsing.py`: parses clean JSON; strips fences; rejects bad schema (mock the API, do not call the network).
- `test_graph_routing.py`: `route_after_tests` returns the right branch for pass, fail with attempts left, and fail at max attempts.
- `test_sandbox.py` (mark `@pytest.mark.docker`, skipped in CI unless Docker is available): a passing repo returns `passed=True`; a failing repo returns `passed=False`; an infinite loop returns `timed_out=True`; network is unavailable inside the container.

---

## 11. Packaging and CI

- `docker-compose.yml`: a service `autopatch` that builds the project image and mounts `/var/run/docker.sock` so the agent can launch sandbox containers; env from `.env`. (Note the security tradeoff in the README.)
- `.github/workflows/ci.yml`: on push/PR run `ruff check`, then `pytest -m "not docker"`. A second job builds the sandbox image and runs `pytest -m docker`.
- `pyproject.toml` with a `[project.scripts]` entry `autopatch = "autopatch.cli:app"`.

---

## 12. Build order (milestones with acceptance criteria)

**M1: Skeleton (about 1 hour).** Repo layout, `pyproject.toml`, config, models, `.env.example`, `.gitignore` (include `.env`, `runs/`), CLI stub that prints help.
*Done when:* `autopatch --help` works.

**M2: Sandbox (about 2 hours).** Dockerfile, `sandbox.py`, `tests/test_sandbox.py`, `autopatch build-sandbox`.
*Done when:* docker tests pass, including timeout and no-network checks.

**M3: Edits and localization (about 2 hours).** `edits.py`, `localize.py` with unit tests.
*Done when:* all edit and localize tests pass.

**M4: LLM layer (about 2 hours).** `prompts.py`, `llm.py`, parsing tests with mocks. One manual smoke test against a real buggy snippet.
*Done when:* the parsing tests pass and a real call returns valid edits.

**M5: LangGraph loop, local mode (about 3 hours).** `graph.py`, `nodes.py`, `logging_utils.py`, `cli.py fix --dry-run`. Create the eval clean repo and bugs 1-3 first.
*Done when:* `autopatch fix --repo eval/clean_repo_with_bug --issue-file issue.md --dry-run` fixes a seeded bug and writes `report.md` and `fix.patch`.

**M6: GitHub PR flow (about 2 hours).** `github_ops.py`, the real run path, PR body template. Test on a throwaway repo you own.
*Done when:* a real issue number produces a real PR, and the guard blocks pushing to the default branch (unit test it).

**M7: Full eval (about 3 hours).** All 10 bugs, `run_eval.py`, `eval/results.md`.
*Done when:* the results table exists with real numbers.

**M8: Polish (about 3 hours).** CI workflow, `docker-compose.yml`, README, optional Streamlit viewer (reads `runs/*/events.jsonl` and shows the step timeline).
*Done when:* a fresh clone can run the demo using only the README.

---

## 13. README requirements

1. One-paragraph pitch plus a GIF or 60-second demo video link
2. Architecture diagram (Mermaid of the Section 7 flow)
3. Quickstart in 3 commands: `cp .env.example .env`, `autopatch build-sandbox`, `autopatch fix ...`
4. Safety design: no-network sandbox, read-only mount, test files protected, PR-only, retry cap
5. Eval results table and how to reproduce it (`autopatch eval`)
6. Limitations: Python and pytest only, stdlib-only target repos, single-file-context heuristics
7. Future work: dependency install phase, multi-language, test generation for the fix, richer repo search

---

## 14. Working rules for Cursor

- Write type hints and short docstrings. Keep functions under 40 lines.
- No secrets in code. No `print` for logs; use `rich` or the event logger.
- After each milestone: run `pytest -m "not docker"`, then `ruff check`, then commit with a clear message.
- Do not add dependencies or features outside this spec without writing the reason in `DECISIONS.md`.
- If a step fails twice, simplify it rather than adding complexity.
- Always keep the project runnable end to end. Prefer a working small loop over a complete unfinished one.

**Start now with M1.**
