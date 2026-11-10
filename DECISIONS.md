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
