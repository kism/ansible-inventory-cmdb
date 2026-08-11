"""Version tracking within the package."""

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

OUR_TIMEZONE = datetime.now().astimezone().tzinfo  # Normal things to do in Python
PROGRAM_START_TIME = datetime.now(tz=OUR_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
PROGRAM_NAME = Path(__file__).parent.name.replace("_", "-").lower()  # Calculate this
PROGRAM_REPO_URL = "https://github.com/kism/ansible-inventory-cmdb"
try:
    PROGRAM_VERSION = version(PROGRAM_NAME)
except PackageNotFoundError:  # pragma: no cover
    PROGRAM_VERSION = "<unknown, please run uv sync>"


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
