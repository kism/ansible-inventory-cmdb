"""Test versioning."""

import tomllib
from pathlib import Path

from ansibleinventorycmdb.constants import PROGRAM_NAME, PROGRAM_REPO_URL, PROGRAM_VERSION


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
