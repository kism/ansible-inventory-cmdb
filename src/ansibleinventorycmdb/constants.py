"""Version tracking within the package."""

from pathlib import Path

PROGRAM_NAME = Path(__file__).parent.name.replace("_", "-").lower()  # Calculate this
PROGRAM_REPO_URL = "https://github.com/kism/ansible-inventory-cmdb"

# Bump this and pyproject.toml together; test__meta.py fails if they drift, and again if uv.lock is stale.
# Not `importlib.metadata.version()`: the Worker bundles this package as plain files with no dist-info
# alongside, so the lookup raises PackageNotFoundError and the deployed site advertises "please run uv sync".
PROGRAM_VERSION = "1.1.1.dev1"


def _get_version_str() -> str:
    """Get a string representation of the version, including branch and commit hash."""
    repo_root = Path(__file__).parent.parent.parent  # src/<pkg>/ -> repo root
    git_head_log = repo_root / ".git" / "logs" / "HEAD"
    git_head = repo_root / ".git" / "HEAD"
    last_commit = ""
    current_branch = ""

    if git_head_log.is_file():
        with git_head_log.open("r") as f:
            lines = f.readlines()
            if lines:  # pragma: no cover # This doesn't get hit in CI
                last_commit = lines[-1].split(" ")[1][:7]  # reflog: "<old> <new> ..."

    if git_head.is_file():
        with git_head.open("r") as f:
            current_branch = f.read().strip().split("/")[-1]

    return (
        f"{PROGRAM_NAME} "
        f"v{PROGRAM_VERSION}"
        f"{('-' + current_branch) if current_branch and (last_commit not in current_branch) else ''}"
        f"{('/' + last_commit + '') if last_commit else ''}"
    )


PROGRAM_NAME_WITH_VERSION = f"{PROGRAM_NAME} v{PROGRAM_VERSION}"
PROGRAM_NAME_WITH_FULL_VERSION = _get_version_str()
