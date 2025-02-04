"""Test versioning."""

import tomlkit

import ansibleinventorycmdb


def test_version():
    """Test version variable."""
    with open("pyproject.toml", "rb") as f:
        pyproject_toml = tomlkit.load(f)
    assert pyproject_toml["project"]["version"] == ansibleinventorycmdb.__version__
