"""Test versioning."""

import tomllib
from pathlib import Path

from ansibleinventorycmdb.constants import (
    COMMIT_SHA_ENV_VAR,
    PROGRAM_NAME,
    PROGRAM_REPO_URL,
    PROGRAM_VERSION,
    version_string,
)


def test_version_pyproject() -> None:
    """Verify version in pyproject.toml matches package version."""
    with Path("pyproject.toml").open("rb") as f:
        pyproject_toml = tomllib.load(f)
    assert pyproject_toml.get("project", {}).get("version", None) == PROGRAM_VERSION


def test_version_lock() -> None:
    """Verify version in uv.lock matches package version."""
    with Path("uv.lock").open("rb") as f:
        uv_lock = tomllib.load(f)

    found_version = False
    for package in uv_lock.get("package", []):
        if package.get("name") == PROGRAM_NAME:
            assert package.get("version") == PROGRAM_VERSION
            found_version = True
            break

    assert found_version, f"{PROGRAM_NAME} not found in uv.lock"


def test_repo_url() -> None:
    """Verify repo URL is correct."""
    with Path("pyproject.toml").open("rb") as f:
        pyproject_toml = tomllib.load(f)
    assert pyproject_toml.get("project", {}).get("urls", {}).get("Repository", None) == PROGRAM_REPO_URL


def test_version_string_commit_sha(monkeypatch) -> None:
    """Verify the build-time commit sha is appended, truncated, and omitted when unset."""
    monkeypatch.delenv(COMMIT_SHA_ENV_VAR, raising=False)
    assert version_string() == f"{PROGRAM_NAME} v{PROGRAM_VERSION}"

    monkeypatch.setenv(COMMIT_SHA_ENV_VAR, "62a8df1e0c4b9a7d5f3")
    assert version_string() == f"{PROGRAM_NAME} v{PROGRAM_VERSION}/62a8df1"
