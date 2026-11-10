"""Shared test setup: skip `docker` tests when the sandbox is not available."""

from __future__ import annotations

import os

import docker
import pytest
from docker.errors import ImageNotFound

from autopatch.config import settings


def _docker_skip_reason() -> str | None:
    """Return why docker tests cannot run, or None if they can."""
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(settings.sandbox_image)
    except ImageNotFound:
        return f"sandbox image {settings.sandbox_image} missing; run `autopatch build-sandbox`"
    except Exception:
        return "Docker daemon not available"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip docker-marked tests without Docker, unless AUTOPATCH_REQUIRE_DOCKER=1."""
    docker_items = [item for item in items if "docker" in item.keywords]
    if not docker_items:
        return
    reason = _docker_skip_reason()
    if reason is None:
        return
    if os.environ.get("AUTOPATCH_REQUIRE_DOCKER") == "1":
        raise pytest.UsageError(f"Docker tests are required but cannot run: {reason}")
    for item in docker_items:
        item.add_marker(pytest.mark.skip(reason=reason))
