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
| Render the static site  | `uv run ansibleinventorycmdb-generate <output dir>`                    |
| Dev server              | `uv run uvicorn ansibleinventorycmdb:create_app --factory --port 5100` |

## Architecture

src layout, installed as a package (hatchling). Imports are `ansibleinventorycmdb.*`, not path-relative.

| Module                                                                         | Role                                                                              |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [`src/ansibleinventorycmdb/__init__.py`](src/ansibleinventorycmdb/__init__.py) | Lazy `create_app` re-export via PEP 562 `__getattr__`, nothing else               |
| [`src/ansibleinventorycmdb/app.py`](src/ansibleinventorycmdb/app.py)          | `create_app()` factory and the lifespan that owns the refresh task                |
| [`src/ansibleinventorycmdb/__main__.py`](src/ansibleinventorycmdb/__main__.py) | `main()`, the `ansibleinventorycmdb` console script, runs uvicorn                 |
| [`src/ansibleinventorycmdb/routes.py`](src/ansibleinventorycmdb/routes.py)     | `APIRouter`, templates, the `HTMLError` page handler, and the CMDB refresh loop   |
| [`src/ansibleinventorycmdb/site.py`](src/ansibleinventorycmdb/site.py)        | Static site renderer, shared by the routes and the Worker. No FastAPI imports     |
| [`src/ansibleinventorycmdb/cmdb.py`](src/ansibleinventorycmdb/cmdb.py)         | `AnsibleCMDB`: fetches inventory URLs, parses hosts/groups/vars, pickle URL cache |
| [`src/ansibleinventorycmdb/config.py`](src/ansibleinventorycmdb/config.py)     | pydantic `Config`/`Inventory` models and `load_config()`                          |
| [`src/ansibleinventorycmdb/logger.py`](src/ansibleinventorycmdb/logger.py)     | `LoggingConfig`, custom logger with TRACE level (5); use `get_logger(__name__)`   |

Templates use `.html.j2` extension (Jinja2). Static assets (CSS, JS, fonts) are in
[`src/ansibleinventorycmdb/static/`](src/ansibleinventorycmdb/static/), mounted at `/static`.

`requires-python` is `>=3.13`, not 3.14, because the Worker runs on Pyodide. On 3.13 annotations are evaluated at
definition time, so any module with a `TYPE_CHECKING`-only import used in a signature needs
`from __future__ import annotations`. Ruff's `TC004` catches this — do not silence it.

### Static site / Cloudflare Worker mode

[`site.py`](src/ansibleinventorycmdb/site.py) renders every page up front instead of per request.
[`worker/`](worker/) is a separate uv project: a cron-triggered Python Worker that builds the CMDB and PUTs the
result into a public R2 bucket. `uv run ansibleinventorycmdb-generate <dir>` does the same thing to a directory.
User-facing docs for this mode live in [README_Wrangler.md](README_Wrangler.md), not README.md.

- `site.py` must not import FastAPI. It is the lower layer; `routes.py` imports `dump_vars`, `group_list` and
  `group_hosts` from it so both modes share one implementation.
- Object keys are the app's URL paths with `/index.html` appended (`inventory/x/host/y/index.html`). The suffix is
  not cosmetic: without it the key `inventory/x` shadows the directory `inventory/x/host/`, which R2's flat
  keyspace tolerates but a filesystem or an `rclone sync` does not.
- Templates take `root_href` and `page_suffix` so the same template emits both link styles. The web app passes
  `"/"` and `""`; the static site passes `"/index.html"` and `"/index.html"`.
- `worker/` is excluded from `ty` and `pyright` in `pyproject.toml`; its `workers` import only resolves inside
  Pyodide.
- **The Worker gets the package by copy, not by dependency.** `pywrangler` resolves dependencies against the
  Pyodide index with `--no-build`, so a path dependency fails, and wrangler does not follow symlinks. The `build`
  command in `wrangler.jsonc` copies `src/ansibleinventorycmdb` next to the entrypoint on every dev and deploy;
  the copy is gitignored. Don't edit it — it is `rm -rf`'d on the next run. `worker/python_modules` is likewise
  generated, re-synced by pywrangler whenever `pyproject.toml`/`pylock.toml` outdate its `.synced` token.
- `worker/pyproject.toml` repeats the package's runtime dependencies by hand and is the one part of `worker/` that
  doesn't self-maintain. `tests/test_worker_deps.py` fails if it drifts from the root `pyproject.toml`; if you add
  a dependency that the Worker genuinely never imports, add it to `NOT_NEEDED_BY_THE_WORKER` there.
- Non-`.py` files need a `rules` entry in `wrangler.jsonc` or they are silently left out of the bundle — that's
  what carries the templates, CSS and fonts.
- Three imports are deferred so the Worker doesn't have to install what it never uses, or can't:
  `create_app`/FastAPI in `__init__.py`, `aiohttp` in `cmdb.aiohttp_fetcher`, and `pwd` in `config._write_config`
  (Pyodide has no `pwd`).
- **`compatibility_date` has two independent ceilings, and the second one is not obvious.** Newer than the workerd
  binary wrangler ships with and `pywrangler dev` won't start. **2026-08-05 or later and the deploy is rejected**
  with `Dynamic require of "fs" is not supported` from `loadPyodide` — Pyodide fails to boot in Cloudflare's
  deploy-time validation. That reproduces on a zero-dependency hello-world Worker, so it is a platform bug, not
  anything in this repo; don't go looking in `entry.py` for it. Pinned to `2026-08-01`, the newest date that
  deploys. Re-bisect before raising it.
- Trigger a local run with `curl http://localhost:8787/cdn-cgi/handler/scheduled`. A *deployed* cron trigger can't
  be fired on demand — `wrangler dev --remote` returns error 1042 rather than dispatching one — which is why
  `entry.py` has a `fetch` handler as well. Both handlers call `_build_and_upload`; keep it that way so the
  ad-hoc path can't drift from the scheduled one.
- The `fetch` handler is guarded by the `BUILD_TOKEN` secret and **fails closed** — no token configured means every
  request 404s. Don't relax this: the `workers.dev` URL is public and each build is ~75 requests against whoever
  hosts the inventory. It returns 404 rather than 403 so it doesn't advertise itself.
- wrangler is pinned in `worker/package.json`, not installed globally — run `npm install` in `worker/` once.
  `pywrangler` shells out to `npx wrangler`, which prefers the local copy. Bumping it may require bumping
  `compatibility_date` too.

### State and dependencies

- The CMDB lives on `app.state.cmdb`, the config on `app.state.config`. There are no module-level globals.
- Page routes take the `CMDB` dependency; JSON routes take `CMDBJson`. Both 500 when the CMDB is missing, the
  difference is whether the error renders as HTML or JSON.
- Page routes signal errors by raising `HTMLError(message, status)`, which `html_error_handler` renders with
  `error.html.j2`. JSON routes raise a plain `HTTPException`.
- `logger` in `__init__.py` is named `_logger`, because `ansibleinventorycmdb.logger` is a submodule.

### Fetching

`AnsibleCMDB.build()`/`refresh()` and everything below them are `async`. Routes stay sync `def` because they only
read the already-built in-memory dicts — they never fetch.

- **HTTP is injected, not hardcoded.** `build(fetch_text)` takes a `Callable[[str], Awaitable[str | None]]` —
  a URL in, the body out, `None` if the response wasn't OK — and threads it down instead of a session. It defaults
  to `aiohttp_fetcher()`, one `aiohttp.ClientSession` per build. **The Worker must pass its own**, because aiohttp
  cannot make a request under Pyodide at all: its connector wants a socket and the `ssl` module, and a Worker has
  neither. The failure is a `RuntimeError("SSL is not supported.")` swallowed into an error dict, so it surfaces as
  an empty CMDB rather than a crash. `aiohttp` is imported inside `aiohttp_fetcher` so the Worker never loads it.
- Per-host and per-group var fetches are `asyncio.gather`ed. The two URLs *within* `_set_host_vars`/`_set_group_vars`
  stay sequential, because the `inventory/` path deliberately overrides the top-level one.
- `CONCURRENT_REQUEST_LIMIT` caps an `asyncio.Semaphore` held across each fetch, recreated per `build()` because
  an asyncio primitive binds to the loop that first awaits it. A semaphore rather than a `TCPConnector` limit
  because the connector isn't in the picture any more. Raising it hammers whatever hosts the inventory.
- The URL cache and the dump are written once at the end of `build()`, via `asyncio.to_thread`. Don't move the cache
  write back into `_get_yaml` — concurrent fetches would race the same file.
- `AnsibleCMDB(inventories)` with no `instance_path` skips the cache and the dump entirely. That's the Worker's
  path: Workers have no writable filesystem, and Pyodide has no threads for `asyncio.to_thread`.
- `_get_yaml` swallows every fetch exception into an `{"error": True, ...}` dict so one dead URL can't fail the whole
  build. Failures are therefore invisible except in the logs — see the test fixtures below. `_usable_inventory`
  exists because that error dict was otherwise walked as if it were an inventory, dying on `True["hosts"]` several
  frames from the real problem.
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
