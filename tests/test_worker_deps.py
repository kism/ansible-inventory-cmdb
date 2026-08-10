"""Guard the one part of worker/ that isn't generated: its hand-written dependency list.

worker/src/ansibleinventorycmdb and worker/python_modules both regenerate themselves (the build command in
wrangler.jsonc, and pywrangler's .synced token). worker/pyproject.toml does not — it repeats this package's runtime
dependencies by hand, because pywrangler resolves against the Pyodide index with --no-build and so cannot take a
path dependency. Adding a dependency here without adding it there gets you a Worker that dies on import at 14:00
UTC and nowhere else.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WORKER_PYPROJECT = REPO_ROOT / "worker" / "pyproject.toml"

# Deferred imports, so the Worker never loads them and doesn't need to install them. Keep in step with the
# lazy imports in __init__.py (create_app) and cmdb.aiohttp_fetcher.
NOT_NEEDED_BY_THE_WORKER = {"fastapi", "uvicorn", "aiohttp"}


def _dependency_names(pyproject: Path) -> set[str]:
    """The bare distribution names in a pyproject's [project.dependencies], without specifiers or extras."""
    dependencies = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    return {re.split(r"[\[><=!~; ]", dependency, maxsplit=1)[0].strip().lower() for dependency in dependencies}


def test_worker_declares_every_dependency_it_needs():
    """Every runtime dependency the Worker can reach must be declared in worker/pyproject.toml."""
    package_deps = _dependency_names(REPO_ROOT / "pyproject.toml")
    worker_deps = _dependency_names(WORKER_PYPROJECT)

    missing = package_deps - NOT_NEEDED_BY_THE_WORKER - worker_deps

    assert not missing, (
        f"{WORKER_PYPROJECT.relative_to(REPO_ROOT)} is missing {sorted(missing)}. Add them there too, or add them "
        f"to NOT_NEEDED_BY_THE_WORKER if the Worker genuinely never imports them."
    )


def test_worker_does_not_ship_what_it_never_imports():
    """The deferred imports must stay out of the Worker bundle, they're megabytes of dead weight."""
    shipped = _dependency_names(WORKER_PYPROJECT) & NOT_NEEDED_BY_THE_WORKER

    assert not shipped, f"worker/pyproject.toml ships {sorted(shipped)}, which the Worker never imports"
