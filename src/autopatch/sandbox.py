"""Run pytest inside a locked-down Docker container (no network, read-only mount)."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import docker
import requests
from docker.errors import APIError, DockerException, ImageNotFound
from docker.models.containers import Container

from .config import settings
from .models import SandboxResult

PYTEST_CMD = ["python", "-m", "pytest", "-x", "-q", "--tb=short", "-p", "no:cacheprovider"]
LOG_TAIL_CHARS = 8000
TIMEOUT_EXIT_CODE = 124


class SandboxError(RuntimeError):
    """The sandbox could not be started (Docker down, image missing, ...)."""


def _client() -> docker.DockerClient:
    """Connect to the Docker daemon or explain why we cannot."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise SandboxError("Cannot reach the Docker daemon. Is Docker running?") from exc


def _start_container(client: docker.DockerClient, repo_path: str) -> Container:
    """Create and start the sandbox container. Never pulls images."""
    try:
        container = client.containers.create(
            settings.sandbox_image,
            PYTEST_CMD,
            working_dir="/work",
            volumes={repo_path: {"bind": "/work", "mode": "ro"}},  # read-only mount
            network_mode="none",
            mem_limit=settings.sandbox_memory,
            nano_cpus=1_000_000_000,
            pids_limit=128,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
        )
    except ImageNotFound as exc:
        raise SandboxError(
            f"Sandbox image '{settings.sandbox_image}' not found. "
            "Build it first with: autopatch build-sandbox"
        ) from exc
    try:
        container.start()
    except APIError as exc:
        container.remove(force=True)
        raise SandboxError(f"Could not start the sandbox container: {exc.explanation}") from exc
    return container


def _wait(container: Container, timeout: int) -> tuple[int, bool]:
    """Wait for the container. Returns (exit_code, timed_out)."""
    try:
        result = container.wait(timeout=timeout)
        return int(result.get("StatusCode", 1)), False
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        try:
            container.kill()
        except APIError:
            pass  # already exited between the timeout and the kill
        return TIMEOUT_EXIT_CODE, True


def run_pytest(repo_path: str, timeout: int | None = None) -> SandboxResult:
    """Run the repo's test suite in the sandbox and return the result."""
    timeout = timeout or settings.sandbox_timeout_seconds
    client = _client()
    start = time.time()
    container = _start_container(client, os.path.realpath(repo_path))
    try:
        exit_code, timed_out = _wait(container, timeout)
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
    finally:
        container.remove(force=True)
    if timed_out:
        logs += f"\n[autopatch] Test run timed out after {timeout}s and was killed.\n"
    return SandboxResult(
        exit_code=exit_code,
        stdout=logs[-LOG_TAIL_CHARS:],
        timed_out=timed_out,
        passed=(exit_code == 0 and not timed_out),
        duration_s=time.time() - start,
    )


def find_dockerfile() -> Path:
    """Locate docker/Dockerfile.sandbox in the cwd or next to the source tree."""
    candidates = [
        Path.cwd() / "docker" / "Dockerfile.sandbox",
        Path(__file__).resolve().parents[2] / "docker" / "Dockerfile.sandbox",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SandboxError("docker/Dockerfile.sandbox not found. Run this from the AutoPatch repo.")


def build_image() -> str:
    """Build the sandbox image and return its tag."""
    dockerfile = find_dockerfile()
    client = _client()
    try:
        # The Dockerfile copies nothing, so send only the file (no build context).
        client.images.build(
            fileobj=io.BytesIO(dockerfile.read_bytes()), tag=settings.sandbox_image, rm=True
        )
    except DockerException as exc:
        raise SandboxError(f"Building the sandbox image failed: {exc}") from exc
    return settings.sandbox_image
