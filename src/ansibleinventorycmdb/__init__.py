"""Present Ansible inventories as a CMDB, either as a web app or as a static site.

`create_app` is imported lazily. Importing it eagerly would drag FastAPI, starlette and uvicorn into every consumer
of this package, including the Cloudflare Worker in worker/, which only wants `cmdb` and `site` and has no use for
a web framework. `ansibleinventorycmdb:create_app` still resolves for uvicorn, via PEP 562.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import create_app  # Re-exported for type checkers; at runtime __getattr__ below resolves it

__all__ = ["create_app"]


def __getattr__(name: str) -> Any:  # noqa: ANN401 Module-level __getattr__ returns whatever the attribute is
    """Resolve `create_app` on first access, so importing this package doesn't import FastAPI."""
    if name == "create_app":
        from .app import create_app  # noqa: PLC0415 That's the point, the import is deferred

        return create_app

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
