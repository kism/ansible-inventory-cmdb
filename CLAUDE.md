# Agent Instructions

FastAPI web app that presents Ansible inventories as a CMDB (Configuration Management Database) webpage. See
[README.md](README.md) for full project overview.

## Setup

```bash
uv sync
```

## Essential Commands

| Task                    | Command                                                                |
| ----------------------- | ---------------------------------------------------------------------- |
| Run tests               | `uv run pytest`                                                        |
| Run tests with coverage | `uv run coverage run && uv run coverage report`                        |
| Lint                    | `uv run ruff check src tests`                                          |
| Format                  | `uv run ruff format src tests`                                         |
| Type check              | `uv run ty check` and `uv run pyright`                                 |
| Dev server              | `uv run uvicorn ansibleinventorycmdb:create_app --factory --port 5100` |

## Architecture

src layout, installed as a package (hatchling). Imports are `ansibleinventorycmdb.*`, not path-relative.

| Module                                                                         | Role                                                                              |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [`src/ansibleinventorycmdb/__init__.py`](src/ansibleinventorycmdb/__init__.py) | `create_app()` factory and the lifespan that starts the refresh thread            |
| [`src/ansibleinventorycmdb/__main__.py`](src/ansibleinventorycmdb/__main__.py) | `main()`, the `ansibleinventorycmdb` console script, runs uvicorn                 |
| [`src/ansibleinventorycmdb/routes.py`](src/ansibleinventorycmdb/routes.py)     | `APIRouter`, templates, the `HTMLError` page handler, and the CMDB refresh loop   |
| [`src/ansibleinventorycmdb/cmdb.py`](src/ansibleinventorycmdb/cmdb.py)         | `AnsibleCMDB`: fetches inventory URLs, parses hosts/groups/vars, pickle URL cache |
| [`src/ansibleinventorycmdb/config.py`](src/ansibleinventorycmdb/config.py)     | pydantic `Config`/`Inventory` models and `load_config()`                          |
| [`src/ansibleinventorycmdb/logger.py`](src/ansibleinventorycmdb/logger.py)     | `LoggingConfig`, custom logger with TRACE level (5); use `get_logger(__name__)`   |

Templates use `.html.j2` extension (Jinja2). Static assets (CSS, JS, fonts) are in
[`src/ansibleinventorycmdb/static/`](src/ansibleinventorycmdb/static/), mounted at `/static`.

### State and dependencies

- The CMDB lives on `app.state.cmdb`, the config on `app.state.config`. There are no module-level globals.
- Page routes take the `CMDB` dependency; JSON routes take `CMDBJson`. Both 500 when the CMDB is missing, the
  difference is whether the error renders as HTML or JSON.
- Page routes signal errors by raising `HTMLError(message, status)`, which `html_error_handler` renders with
  `error.html.j2`. JSON routes raise a plain `HTTPException`.
- Routes are sync `def`, so blocking `requests` calls run in FastAPI's threadpool. Don't make them `async def`
  without also making `cmdb.py` async.
- `logger` in `__init__.py` is named `_logger`, because `ansibleinventorycmdb.logger` is a submodule.

## Configuration

Config file: `instance/config.yml`. See [instance/config.yml](instance/config.yml) for the canonical example.
Key sections: `cmdb` (inventory URLs + schema_mapping) and `logging`.

All models set `extra="forbid"`, so an unknown key is a startup failure, not a warning. Adding a config option means
adding a field to the model in [`config.py`](src/ansibleinventorycmdb/config.py).

The instance path defaults to `./instance`, overridable with `AIC_INSTANCE_PATH`.

## Testing

```bash
uv run pytest                   # runs all tests
uv run pytest -k test_name      # single test
uv run pytest --random-order    # order independence
```

- **All HTTP requests are mocked** via an auto-use fixture in [`tests/conftest.py`](tests/conftest.py) — add new URLs
  to the mock list when adding inventory URL tests. The `error_on_unfetchable_url` auto-use fixture fails the test if
  you forget, since `AnsibleCMDB` deliberately swallows fetch errors.
- The `client` fixture does **not** enter the TestClient context, so the lifespan and its refresh thread don't run.
  A thread still fetching when `requests_mock` unpatches at teardown makes real network requests and flakes other
  tests. `test_lifespan_builds_cmdb` covers the lifespan and waits for the build before leaving the context.
- Always pass `tmp_path` as `instance_path`; the `app` fixture asserts this. Tests that build their own
  `AnsibleCMDB` need their own subdirectory, or its `url_cache.pkl` collides with the app's.
- Test configs live in [`tests/configs/`](tests/configs/); test inventories in [`tests/inventories/`](tests/inventories/).

## Code Conventions

- **Type hints** required on all functions; enforced by ruff (`ANN` rules, relaxed in tests).
- **Google-style docstrings** required on all modules, classes, and public functions.
- **Double quotes**, max line length **120**.
- `ruff` is configured with `select = ["ALL"]` and selective ignores — run `ruff check` before committing.
- Module logger: `logger = get_logger(__name__)` at module level.
