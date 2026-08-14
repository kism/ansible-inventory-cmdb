"""Version tracking within the package."""

import os
from pathlib import Path

PROGRAM_NAME = Path(__file__).parent.name.replace("_", "-").lower()  # Calculate this
PROGRAM_REPO_URL = "https://github.com/kism/ansible-inventory-cmdb"

# Bump this and pyproject.toml together; test__meta.py fails if they drift, and again if uv.lock is stale.
# Not `importlib.metadata.version()`: the Worker bundles this package as plain files with no dist-info
# alongside, so the lookup raises PackageNotFoundError and the deployed site advertises "please run uv sync".
PROGRAM_VERSION = "1.1.1.dev1"

PROGRAM_NAME_WITH_VERSION = f"{PROGRAM_NAME} v{PROGRAM_VERSION}"

# Supplied at build time, because neither of the two places the version is actually read from ships a .git to
# look in: an installed wheel and the Worker bundle are both just the package's files. Set it in the environment
# for the server and for `ansibleinventorycmdb-generate`; the Worker gets it from a wrangler var, see entry.py.
COMMIT_SHA_ENV_VAR = "AIC_COMMIT_SHA"


def version_string() -> str:
    """Program name, version, and the build's commit sha if one was supplied. Shown in the page footer."""
    sha = os.environ.get(COMMIT_SHA_ENV_VAR, "")[:7]
    return f"{PROGRAM_NAME_WITH_VERSION}/{sha}" if sha else PROGRAM_NAME_WITH_VERSION
