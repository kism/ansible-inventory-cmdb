"""Test versioning."""

import tomllib
from pathlib import Path

import ansibleinventorycmdb


def test_version_pyproject() -> None:
    """Verify version in pyproject.toml matches package version."""
    pyproject_path = Path("pyproject.toml")
    with pyproject_path.open("rb") as f:
        pyproject_toml = tomllib.load(f)
    assert pyproject_toml.get("project", {}).get("version", None) == ansibleinventorycmdb.__version__


def test_version_lock() -> None:
    """Verify version in uv.lock matches package version."""
    lock_path = Path("uv.lock")
    with lock_path.open("rb") as f:
        uv_lock = tomllib.load(f)

    found_version = False
    for package in uv_lock.get("package", []):
        if package.get("name") == "ansibleinventorycmdb":
            assert package.get("version") == ansibleinventorycmdb.__version__
            found_version = True
            break

    assert found_version, "ansibleinventorycmdb not found in uv.lock"
