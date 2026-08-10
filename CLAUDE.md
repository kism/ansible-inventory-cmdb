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
| [`src/ansibleinventorycmdb/__init__.py`](src/ansibleinventorycmdb/__init__.py) | `create_app()` factory and the lifespan that owns the refresh task                |
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
- `logger` in `__init__.py` is named `_logger`, because `ansibleinventorycmdb.logger` is a submodule.

### Fetching

`AnsibleCMDB.build()`/`refresh()` and everything below them are `async`, using `aiohttp`. Routes stay sync `def`
because they only read the already-built in-memory dicts — they never fetch.

- One `ClientSession` is created per `build()` and threaded down as an explicit parameter. Nothing holds a session
  between builds.
- Per-host and per-group var fetches are `asyncio.gather`ed. The two URLs *within* `_set_host_vars`/`_set_group_vars`
  stay sequential, because the `inventory/` path deliberately overrides the top-level one.
- `CONCURRENT_REQUEST_LIMIT` caps the connector. Raising it hammers whatever hosts the inventory.
- The URL cache and the dump are written once at the end of `build()`, via `asyncio.to_thread`. Don't move the cache
  write back into `_get_yaml` — concurrent fetches would race the same file.
- `_get_yaml` swallows every fetch exception into an `{"error": True, ...}` dict so one dead URL can't fail the whole
  build. Failures are therefore invisible except in the logs — see the test fixtures below.
- The background refresh is an `asyncio.Task` created in the lifespan and cancelled on shutdown. It catches and logs
  its own exceptions; nothing awaits it, so an uncaught one would be silent.

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

- **Inventory fetches hit a real local HTTP server**, not a mocking library — `inventory_server` in
  [`tests/conftest.py`](tests/conftest.py) serves the fixture inventory on a random port. aiohttp mocking libraries
  (aioresponses) patch aiohttp internals and are broken against aiohttp 3.14; a socket is not.
- Test configs use `https://pytest.internal` as a placeholder, which `get_test_config` rewrites to the live server
  address. Add new paths to `EMPTY_VAR_PATHS`; the `mock_get_inventory_url` auto-use fixture fails the test on any
  path the server didn't recognise, so a missing entry can't silently become empty data.
- `build_cmdb` runs the async `refresh()` from a sync test via `asyncio.run`. There is no pytest-asyncio.
- The `client` fixture does **not** enter the TestClient context, so the lifespan and its refresh task don't run.
  `test_lifespan_builds_cmdb` covers the lifespan and waits for the build before leaving the context.
- Always pass `tmp_path` as `instance_path`; the `app` fixture asserts this. Tests that build their own
  `AnsibleCMDB` need their own subdirectory, or its `url_cache.pkl` collides with the app's.
- Test configs live in [`tests/configs/`](tests/configs/); test inventories in [`tests/inventories/`](tests/inventories/).

## Code Conventions

- **Type hints** required on all functions; enforced by ruff (`ANN` rules, relaxed in tests).
- **Google-style docstrings** required on all modules, classes, and public functions.
- **Double quotes**, max line length **120**.
- `ruff` is configured with `select = ["ALL"]` and selective ignores — run `ruff check` before committing.
- Module logger: `logger = get_logger(__name__)` at module level.
