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
