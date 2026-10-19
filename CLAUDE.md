# Agent Instructions

Presents Ansible inventories as a CMDB (Configuration Management Database) webpage. See
[README.md](README.md) for full project overview.

## Setup

```bash
uv sync                     # Cloudflare Worker mode
uv sync --extra server      # ...plus the FastAPI web app
nvm install                 # node 26, from .nvmrc
pnpm install                # wrangler, biome, vite and typescript, pinned in package.json; pnpm itself by packageManager
pnpm build                  # the frontend, into frontend/dist, which the web app serves
scripts/build-token.sh set  # BUILD_TOKEN, needed before the Worker's /refresh endpoint works
```

**Every command is a pnpm script** in `package.json`: the Python checks (`lint`, `format`, `typecheck`, `test`,
`coverage`) wrap `uv run`, the frontend ones (`build`, `build:cf`, `frontend`, `test:frontend`) wrap vite and
node, and the Cloudflare ones (`login`, `bucket`, `domain`, `cors`, `dev`, `deploy`, `tail`) wrap wrangler.
`wrangler` and `uv run pywrangler` are what those scripts call; don't put them in docs or suggest them to the
user. `pywrangler` proxies any subcommand it doesn't handle straight to `npx wrangler`, and syncs
`python_modules` first for `dev`/`deploy` — the reason those two don't call wrangler directly.

**`deploy` and `login` are pnpm built-ins**, so they must be run as `pnpm run deploy` / `pnpm run login`; a bare
`pnpm deploy` runs pnpm's own workspace deploy instead. Every other script works as `pnpm <name>`.

pnpm only runs dependency install scripts approved in `pnpm-workspace.yaml` (`allowBuilds`). If a new dependency
needs one, `pnpm install` stops and names it; approve it with `pnpm approve-builds <package>`.

One `pyproject.toml` covers both hosts. **`[project.dependencies]` is the Worker's install list** — pywrangler
reads it and nothing else (no extras, no dependency-groups) and resolves it against the Pyodide index, so anything
the Worker can't run belongs in the `server` extra. See *Dependency layout* below.

## Essential Commands

| Task                    | Command                                                                    |
| ----------------------- | -------------------------------------------------------------------------- |
| Run tests               | `pnpm test` (args go to pytest: `pnpm test -k name`)                       |
| Run tests with coverage | `pnpm coverage`                                                            |
| Frontend tests          | `pnpm test:frontend` (`node --test`, no test framework)                    |
| Lint                    | `pnpm lint` (biome, ruff check, ruff format --check)                       |
| Format                  | `pnpm format` (biome --write, ruff format, ruff check --fix)               |
| Type check              | `pnpm typecheck` (ty, then tsc on the frontend)                            |
| Everything CI runs      | `scripts/run-ci-local.sh`                                                  |
| Build the frontend      | `pnpm build` (API at `/api`), `pnpm build:cf` (API at cmdb-api)            |
| Dev server              | `uv run uvicorn ansibleinventorycmdb.app:create_app --factory --port 5100` |
| Frontend dev server     | `pnpm frontend` (Vite with HMR, proxies `/api` to the dev server above)    |
| Worker dev / deploy     | `pnpm dev` / `pnpm run deploy` (from the repo root)                        |
| Check the Worker boots  | `pnpm check_worker` (from the repo root)                                   |

Biome lints and formats everything that isn't Python — the frontend's TypeScript, `zy.css`, the
JSON(C) — with the same 120 columns as ruff. CI has one workflow per check (`lint.yml`, `check_types.yml`,
`test.yml`, `build.yml`), so a failing badge names what broke; `build.yml` is `check_worker` and the frontend's
tsc, tests and build.

## Architecture

Two hosts serve one JSON API and one frontend, and neither is a port of the other:

```
                       api.build_api(config, fetch)  →  {key: json bytes}
             ┌──────────────────────┴───────────────────────┐
 web app: /api/<key> from memory                  Worker: cron PUTs <key> to R2 → cmdb-api.kierangee.au
          /*  → frontend/dist (SPA fallback)              static assets → cmdb.kierangee.au (SPA fallback)
          6h refresh loop (lifespan)                      /refresh, /status → entry.py
```

The Python builds the CMDB and renders it to a fixed set of JSON objects, once per build. The frontend, a
TypeScript SPA, renders every page in the browser from them. Each host keeps the objects its own native way
(process memory vs an R2 bucket), refreshes on its own native schedule (an asyncio task vs a cron trigger) and
serves the frontend its own native way (`StaticFiles` vs Workers Static Assets); the bytes are identical.

src layout, installed as a package (hatchling). Imports are `ansibleinventorycmdb.*`, not path-relative.

| Module                                                                         | Role                                                                              |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| [`src/ansibleinventorycmdb/__init__.py`](src/ansibleinventorycmdb/__init__.py) | Docstring only. Importing the package must not pull in FastAPI, see below          |
| [`src/ansibleinventorycmdb/app.py`](src/ansibleinventorycmdb/app.py)          | `create_app()`, the lifespan that owns the refresh task, `SPAStaticFiles`         |
| [`src/ansibleinventorycmdb/__main__.py`](src/ansibleinventorycmdb/__main__.py) | `main()`, the `ansibleinventorycmdb` console script, runs uvicorn                 |
| [`src/ansibleinventorycmdb/routes.py`](src/ansibleinventorycmdb/routes.py)     | `APIRouter`: `/api/{key}` out of memory, `/status`, `/health`, the refresh loop  |
| [`src/ansibleinventorycmdb/api.py`](src/ansibleinventorycmdb/api.py)          | The API renderer both hosts build through. No FastAPI imports                     |
| [`src/ansibleinventorycmdb/cmdb.py`](src/ansibleinventorycmdb/cmdb.py)         | `AnsibleCMDB`: fetches inventory URLs, parses hosts/groups/vars, per-build URL cache |
| [`src/ansibleinventorycmdb/config.py`](src/ansibleinventorycmdb/config.py)     | pydantic `Config`/`Inventory` models and `load_config()`                          |
| [`src/ansibleinventorycmdb/logger.py`](src/ansibleinventorycmdb/logger.py)     | `LoggingConfig` and `setup_logger`: one console handler, optionally a file one     |
| [`src/entry.py`](src/entry.py)                                                | The Cloudflare Worker's entrypoint. Not part of the package, see below           |
| [`frontend/`](frontend/)                                                      | The TypeScript SPA (Vite, no framework). Not part of the package either          |

`requires-python` is `>=3.13`, a floor below the 3.14 the Worker's Pyodide now runs. On 3.13 annotations are
evaluated at definition time, so any module with a `TYPE_CHECKING`-only import used in a signature needs
`from __future__ import annotations`. Ruff's `TC004` catches this — do not silence it.

### The API

[`api.py`](src/ansibleinventorycmdb/api.py) renders every object up front: `build_api()` builds an
`AnsibleCMDB` and returns `{key: body}` from `render_api()`. The web app serves that dict at `/api/<key>`; the
Worker PUTs it into R2 at `<key>`. **Both hosts go through `build_api`**, which is what keeps them from drifting —
`test_serves_every_object` checks the web app returns every object byte for byte.

| Key                                         | Body                                                   |
| ------------------------------------------- | ------------------------------------------------------ |
| `inventories.json`                          | `{version, repo_url, built_at, inventories: {name: {url, base_url}}}` |
| `inventory/{name}.json`                     | `{schema_mapping, groups, hosts: {host: {groups, vars}}}` |
| `inventory/{name}/host/{host}.json`         | `{groups, vars, vars_yaml}`                            |
| `inventory/{name}/group/{group}.json`       | `{vars, vars_yaml}`                                    |
| `inventory/{name}/group/{group}/hosts.json` | hostname → vars for the group; `all` included          |

- `api.py` must not import FastAPI. It is the lower layer, and the Worker doesn't install FastAPI.
- **Every key ends in `.json`.** That's what keeps `inventory/x.json` from shadowing the "directory"
  `inventory/x/` its children live in — R2's flat keyspace tolerates that, a filesystem doesn't — and why R2
  needs no index document or rewrite rule. The frontend builds keys out of names in other objects;
  `test_every_reference_resolves` checks every one it can build was written. Change the scheme in both places.
- `vars_yaml` is `dump_vars()` output, pre-rendered in Python, so the vars pages show the same yaml (dates, `|`
  blocks, sorted keys) without a YAML library in the browser. The JSON is `json.dumps(default=str)`, because
  `yaml.safe_load` turns an unquoted date into a `date`, which plain `json.dumps` refuses.
- `api_status()` is the `/status` body both hosts return, 503 when stale. Each passes its own last build time
  (its clock / R2's upload time) and threshold (its refresh interval plus two hours of slack).
- There used to be a server-rendered HTML site (Jinja templates, `root_href`/`page_suffix` link styles, a
  `generate` CLI) and a zone-level URL Rewrite appending `index.html` for the bucket. All gone with the move to
  JSON; don't bring them back.

### The frontend

[`frontend/src/main.ts`](frontend/src/main.ts) routes on `location.pathname`, fetches the one API object a page
needs, and renders it into `#app`. `get()` keeps every response in a per-tab `Map`, and the inventory view prefetches
all its host and group objects at low fetch priority, so clicking through renders from memory. Built by Vite into `frontend/dist/` (gitignored).

- **Every interpolation goes through `` html`...` ``** ([`html.ts`](frontend/src/html.ts)), which escapes
  anything that isn't another `html` fragment. Inventory values come from someone's git repo and end up in
  `innerHTML`; this is the job Jinja's autoescape used to do. Never build markup out of a plain template string.
- **The API base is a build-time constant**: `import.meta.env.VITE_API_BASE ?? "/api"`. `pnpm build` leaves it
  unset, which is the web app's own `/api`. `pnpm build:cf` is `--mode cloudflare`, which reads
  [`frontend/.env.cloudflare`](frontend/.env.cloudflare) (tracked) and points at `https://cmdb-api.kierangee.au`.
  wrangler's `build.command` runs `build:cf`, so `pnpm dev`, deploy and Workers Builds previews always get it.
- **Both hosts answer any non-file path with `index.html`** — `SPAStaticFiles` in the web app,
  `not_found_handling: single-page-application` on the Worker — which is how a reload on
  `/inventory/x/host/y` works. A click on an in-app link is caught and rendered with pushState; off-site links and the API's own JSON
  links are left to the browser. The router strips a
  trailing `/index.html`, so links into the old static site still land.
- `frontend/public/` is copied into `dist/` as is, so `public/static/` is served at `/static/`.
- The hosts table sorts by a heading's column on click and by `IP Address` on render
  ([`sort.ts`](frontend/src/sort.ts)), from `render()` and a delegated listener — no inline `onclick`, since the
  markup is `innerHTML`. It used to be a classic `sorttable.js`, whose sort-on-load ran before the SPA had
  rendered the table.
- Imports carry their `.ts` extension (`allowImportingTsExtensions`, `erasableSyntaxOnly`), so `node --test`
  runs the same files under Node 26's type stripping with no test framework. `*.test.ts` is excluded from tsc,
  which would otherwise need `@types/node` for two imports. Root `package.json` is `"type": "module"` for the
  same reason, and so Vite loads its config as ESM.
- The web app serves `FRONTEND_DIR`, `frontend/dist` in the checkout — it's not shipped in the wheel. Missing,
  it logs a warning and serves the API only.

The fonts are the `@fontsource/fira-code`/`@fontsource/noto-sans-display` devDependencies, imported as CSS at the
top of `main.ts`, so Vite bundles the `@font-face` rules and the woff2 files into `dist/assets/` with hashed names.
Adding a weight is adding an import. There used to be checked-in woff2 copies, a script to refresh them and a CI
check that they existed; all gone, since a missing file is now a build error.

### Cloudflare Worker mode

[`src/entry.py`](src/entry.py) is a cron-triggered Python Worker that runs `build_api` and PUTs the result into a
public R2 bucket, served at cmdb-api.kierangee.au. The same Worker's static assets are the frontend, at
cmdb.kierangee.au. User-facing docs for this mode live in [README_Wrangler.md](README_Wrangler.md) (deploying)
and [README_Wrangler_dev.md](README_Wrangler_dev.md) (local dev, layout, dependency rules), not README.md.

- **Two domains, two mechanisms.** The frontend's is a Worker custom domain, `routes` in `wrangler.jsonc`. The
  API's is the bucket's custom domain, `pnpm domain`, with a CORS policy from
  [`r2-cors.json`](r2-cors.json) (`pnpm cors`, GET/HEAD from `*`: the data is public, and a named origin would
  also block the frontend's `workers.dev` copy). Page views never run the Python.
- **`workers_dev` and `preview_urls` are set explicitly** because declaring `routes` silently turns both off — the
  first deploy with the custom domain did exactly that, and `scripts/build-token.sh`'s `WORKER_URL` stopped
  resolving. Don't drop them as "defaults".
- **After the puts, `_prune` deletes every key the build didn't write.** A host dropped from the inventory
  would otherwise keep serving its JSON forever, and the first JSON build cleared out the old HTML site this way.
  It runs after the puts, so a build that died partway has already raised and deleted nothing. Through the
  Workers SDK, a plain JS object comes back as a dict (`listed["objects"]`) while R2Object instances keep
  attribute access (`obj.key`, `index.uploaded`).
- `run_worker_first: ["/refresh", "/status"]` in `assets`: at this `compatibility_date` the SPA fallback serves
  `index.html` to *navigation* requests before the Worker sees them, which would turn the bookmarkable
  `/refresh?token=` URL into the home page.
- **`wrangler.jsonc` has to sit next to `pyproject.toml`.** pywrangler takes the directory of the nearest
  `pyproject.toml` above the cwd as the project root and looks for the wrangler config *there*; `pylock.toml`,
  `python_modules/` and `.venv-workers/` are written there too. That's why all of it is at the repo root and there
  is no `worker/` directory.
- **The Worker bundles the package because it's a sibling of the entrypoint, not because of a build step.**
  wrangler's `base_dir` defaults to the entrypoint's directory, so `main: src/entry.py` makes `src/ansibleinventorycmdb`
  bundle at the same path it is imported from. There used to be an `rm -rf` + `cp -r` build command faking this;
  don't bring it back. `.pyc` files aren't a problem — no module rule matches them.
- `src/entry.py` is excluded from `ty` in `pyproject.toml`; its `workers` import only resolves inside
  Pyodide. It is deliberately *not* inside the package: in the bundle it's a top-level module, so it needs the
  absolute `ansibleinventorycmdb.*` imports it has.
- **The deployment is the repo**, not arguments to `deploy`: `wrangler.jsonc` holds the bucket, cron, assets,
  module rules and the frontend's domain, `src/config.yml` the inventories, `frontend/.env.cloudflare` the API's
  URL, `package.json`'s `domain`/`cors` scripts the API's domain and CORS (`r2-cors.json`). Deploying elsewhere
  means forking and editing those.
- Non-`.py` files need a `rules` entry in `wrangler.jsonc` or they are silently left out of the bundle — that's
  what carries `src/config.yml`, the only one left. The frontend isn't bundled into the Python at all, it's
  `assets`.
- **`src/config.yml` is tracked, and it is the Worker's whole config.** A Worker has no instance path at runtime
  and no writable filesystem for `load_config`'s write-the-defaults fallback, so `entry.py` parses this file
  directly at import; wrangler can only bundle what's under `base_dir` (`src/`), which is why it lives there.
  It used to be a gitignored symlink to `instance/config.yml`; **don't reintroduce that.** The deployment is meant
  to be the repo — a fork changes the files above and nothing else — and a checkout with no config produced a
  bundle that died on import with `FileNotFoundError` on `/session/metadata/config.yml`, because wrangler drops a
  `rules` glob that matches nothing without a word. There is nothing secret in it: everything it builds is served
  publicly. The web app still reads `instance/config.yml` via `load_config()`; that path is untouched.
- The Worker must not have to install what it never uses, or can't. `__init__.py` is empty so importing the
  package reaches no FastAPI — the uvicorn target is `ansibleinventorycmdb.app:create_app`, not
  `ansibleinventorycmdb:create_app`; there was a PEP 562 `__getattr__` shim faking the short form, don't bring it
  back. `httpx` is imported inside `cmdb.httpx_fetcher`, and `pwd` inside `config._write_config` (no `pwd` in
  Pyodide).
- **`compatibility_date` selects the edge's Python runtime, and it has a floor as well as a ceiling.**
  pywrangler's `metadata.py` maps the date to a version: **2026-09-08 or later is Python 3.14**, anything older
  is 3.13. The 3.13 edge runtime does not put the bundled `python_modules` on `sys.path`, so the deploy is
  rejected with `ModuleNotFoundError` on the *first* vendored import (`import yaml`, in `entry.py`) while
  `pnpm dev` boots the same bundle happily — workerd locally is fine with it. That is what the stale
  `2026-08-01` pin here caused; don't lower it back. The ceiling is still the workerd binary wrangler ships
  with: newer than that and `pnpm dev` won't start. The date also picks the Pyodide index the wheels come
  from, so after changing it delete `pylock.toml` (it pins the old ones), run `uv run pywrangler sync --force`,
  and re-run `pnpm check_worker`.
- **The same `ModuleNotFoundError: No module named 'yaml'` also means `python_modules/` wasn't there.** It is
  gitignored and written by `pywrangler sync`, which `pnpm run deploy` runs first; a git-connected Workers Builds
  deploy left on the stock `npx wrangler deploy` skips it, and wrangler then ships a bundle with **no** vendored
  packages rather than erroring (the missing directory is a debug-level log line). Tell the two causes apart by
  `Total Upload`: ~8 MB with the packages, a few hundred KiB without. Build settings in README_Wrangler.md.
- Trigger a local run with `curl http://localhost:8787/cdn-cgi/handler/scheduled`. A *deployed* cron trigger can't
  be fired on demand — `wrangler dev --remote` returns error 1042 rather than dispatching one — which is why
  `entry.py` has a `fetch` handler as well. Both handlers call `_build_and_upload`; keep it that way so the
  ad-hoc path can't drift from the scheduled one.
- The `fetch` handler serves exactly two paths, `/refresh` (build) and `/status`; anything else gets the same 404
  as a bad token. `/refresh` is guarded by the `BUILD_TOKEN` secret and **fails closed** — no token configured means
  every request 404s. Don't relax this: the `workers.dev` URL is public and each build pulls a whole repo down from
  whoever hosts the inventory. It returns 404 rather than 403 so it doesn't advertise itself. The token is taken from
  either the `Authorization` header or `?token=`, because the dashboard has no way to fire a cron trigger or set a
  header — a bookmarkable URL is the only trigger a browser can offer. Compare as `bytes`:
  `hmac.compare_digest` raises `TypeError` on non-ASCII `str`, which would turn a junk token into a 500.
- `/status` is the one path in front of that guard. It **stores nothing**: it heads `inventories.json`, which
  every build rewrites, so its upload time is the last successful run — a failed build writes nothing and shows
  up as a growing `age_seconds`. Don't add a status object written per run to record failures too; it answers
  the same question with state that can go stale. Unauthenticated because the bucket is public, and 503 past
  `STALE_AFTER_SECONDS` so a dumb uptime monitor works. The binding returns `uploaded` as a **naive** `datetime`
  in UTC — `.replace(tzinfo=UTC)`, or subtracting from `now(UTC)` raises.
- wrangler is pinned in `package.json`, not installed globally — run `pnpm install` at the repo root once.
  `pywrangler` shells out to `npx wrangler`, which prefers the copy pnpm links into `node_modules/.bin`. Bumping
  it may require bumping `compatibility_date` too.

### Dependency layout

One `pyproject.toml`, both hosts. `pywrangler`'s `parse_requirements()` reads **only `[project.dependencies]`** —
extras and dependency-groups are invisible to it — and compiles that list against the Pyodide index with
`--no-build`. So that list is exactly "what the Worker installs", and it is load-bearing:

- `[project.dependencies]`: `httpx`, `pydantic`, `pyyaml`. All three have Pyodide wheels. Adding something
  here without a Pyodide wheel breaks `pnpm dev`/`deploy` at the resolve step, not at runtime. So does raising
  a floor past what the index for the current `compatibility_date` serves — `pydantic>=2.11` did exactly that
  back when the 3.13 index stopped at 2.10.6; the 3.14 index serves 2.12.5.
  `pnpm check_worker` ([`scripts/check-worker.sh`](scripts/check-worker.sh), also a CI job) is what catches
  both: it starts `pnpm dev` — which resolves the list, builds the frontend, then boots the bundle in workerd —
  and fails unless an untokened `/refresh` comes back 404, `/status` returns its JSON, and the frontend is served
  from assets. Nothing in pytest runs a line of this under Pyodide.
- `[project.optional-dependencies].server`: `fastapi`, `uvicorn`. `uv sync --extra server`. The `test`
  dependency-group pulls it in as `ansibleinventorycmdb[server]`, so `uv sync` for development still gets it.
- `[dependency-groups].worker`: `workers-py`, `workers-runtime-sdk`. In `default-groups`, so `uv run pywrangler`
  works after a plain `uv sync`. CI passes `--no-group worker`.
- **`aiohttp` is not an option here.** `aiohttp>=3.14.3` has no usable wasm wheel at all, and unpinned it resolves
  to the socket-based build that dies under Pyodide with `RuntimeError("SSL is not supported.")`. The Pyodide index
  serves its *own* `httpx` wheel (different sha256 from PyPI's, and no `httpcore`/`anyio`/`certifi` in its
  metadata) patched to use the JS `fetch` API, which is why httpx is the one that works in both places.
- The frontend's dependencies are devDependencies in the root `package.json` (`vite`, `typescript`); it has no
  runtime ones. One `package.json`, no workspace.

### State and dependencies

- The API lives on `app.state.api` — `dict[str, bytes]`, object key to JSON body, `None` until the first build
  lands — and its build time on `app.state.built_at`. The config is on `app.state.config`. There are no
  module-level globals.
- `/api/{key}` 503s before the first build and 404s for an unknown key, as plain `HTTPException`s. There are no
  HTML error pages: the frontend renders a failed fetch itself.
- The refresh task replaces `app.state.api` only once a build has succeeded, so a failed build keeps serving the
  last good one — the same as the bucket does.
- The frontend is mounted at `/` *after* the router, so API routes are matched first and an API miss stays an
  API error rather than becoming `index.html`.
- `logger` in `app.py` is named `_logger`, because `ansibleinventorycmdb.logger` is a submodule.

### Fetching

`AnsibleCMDB.build()`/`refresh()` and everything below them are `async`. Routes stay sync `def` because they only
read the already-built `app.state.api` — they never fetch.

- **HTTP is injected, not hardcoded.** `build(fetch_text)` takes a `Callable[[str], Awaitable[str | None]]` —
  a URL in, the body out, `None` if the response wasn't OK — and threads it down instead of a session. It defaults
  to `httpx_fetcher()`, one `httpx.AsyncClient` per build; `entry.py` passes `github_zip_fetcher` over the Workers
  runtime's `fetch` instead, which is the path that's actually been run in a Worker. `httpx` is imported inside
  `httpx_fetcher`, so the Worker never loads it. `build_api(config, fetch_text)` passes it straight through.
- **`github_zip_fetcher` is what keeps the Worker under the free plan's subrequest limit.** A build probes every
  host and group at two paths, ~80 requests for the real inventory, and the free plan allows **50 external
  subrequests per invocation** — that's the `Too many subrequests` exception. It serves
  `raw.githubusercontent.com` URLs out of one `codeload.github.com` zip per repo instead, so a build costs one
  external subrequest. The R2 calls don't compete with it: requests to Cloudflare services have their own 1000
  budget. Non-GitHub URLs, unreadable zips and branch names containing `/` fall back to a request per file, so
  the fetcher is safe to hand any config. `limits.subrequests` in `wrangler.jsonc` does **not** help — the free
  plan's 50 is a ceiling, not a default.
- `httpx_fetcher` needs `follow_redirects=True` (httpx doesn't redirect by default, aiohttp did) and must **not**
  call `raise_for_status()`. A host or group with no vars file 404s on every single build — that's the normal case,
  and it has to come back as `None`, not an exception. httpx's own INFO logging is turned down in `logger.py`,
  it logs a line per request.
- Per-host and per-group var fetches are `asyncio.gather`ed. The two URLs *within* `_set_host_vars`/`_set_group_vars`
  stay sequential, because the `inventory/` path deliberately overrides the top-level one.
- `CONCURRENT_REQUEST_LIMIT` caps an `asyncio.Semaphore` held across each fetch, recreated per `build()` because
  an asyncio primitive binds to the loop that first awaits it. A semaphore rather than a client-level connection
  limit, because the client isn't in the picture on the Worker's path. Raising it hammers whatever hosts the
  inventory.
- **`AnsibleCMDB` writes nothing to disk, in any mode.** `url_cache` dedupes fetches *within* one build — a
  group's vars file is otherwise probed once per host in it — and is dropped after. There used to be a pickled
  `url_cache.pkl` and a `cmdb_dump.yml` under the instance path; don't reintroduce either. Nothing read the dump,
  and the pickle's only effect was that the first pages after a restart served yesterday's data before the real
  build replaced it. It also means no `instance_path` argument, no `asyncio.to_thread` (Pyodide has no threads)
  and no special case for the Worker's read-only filesystem.
- `_get_yaml` swallows every fetch exception into an `{"error": True, ...}` dict so one dead URL can't fail the whole
  build. Failures are therefore invisible except in the logs — see the test fixtures below. `_usable_inventory`
  exists because that error dict was otherwise walked as if it were an inventory, dying on `True["hosts"]` several
  frames from the real problem.
- The background refresh is an `asyncio.Task` created in the lifespan and cancelled on shutdown. It catches and logs
  its own exceptions; nothing awaits it, so an uncaught one would be silent.

## Configuration

Two files, same schema, one `Config` model. The web app loads `instance/config.yml` (gitignored) via
`load_config()`; the Worker parses the tracked [`src/config.yml`](src/config.yml) at import. Key sections: `cmdb`
(inventory URLs + schema_mapping) and `logging`. The frontend's only setting is its API base, see above.

All models set `extra="forbid"`, so an unknown key is a startup failure, not a warning. Adding a config option means
adding a field to the model in [`config.py`](src/ansibleinventorycmdb/config.py).

The instance path defaults to `./instance`, overridable with `AIC_INSTANCE_PATH`.

`AIC_COMMIT_SHA` is read by `constants.version_string()`, which `inventories.json` carries for the footer. It is an
environment variable rather than something read out of `.git`, because the two places it's actually read — an
installed wheel and the Worker bundle — are just the package's files, with no repo alongside. `pnpm run deploy`
passes the sha as a wrangler `--var`, and `entry.py` copies that var into `os.environ` in `_build_and_upload`; a
wrangler var only exists on `env`, which the runtime hands to a handler, so it can't be picked up at import time.

## Testing

```bash
uv run pytest                   # runs all tests
uv run pytest -k test_name      # single test
uv run pytest --random-order    # order independence
pnpm test:frontend              # the frontend's node --test files
```

- **Inventory fetches hit a real local HTTP server**, not a mocking library — `inventory_server` in
  [`tests/conftest.py`](tests/conftest.py) serves the fixture inventory on a random port. HTTP mocking libraries
  patch client internals and break on the client's minor releases; a socket does not.
- Test configs use `https://pytest.internal` as a placeholder, which `get_test_config` rewrites to the live server
  address. Add new paths to `EMPTY_VAR_PATHS`; the `mock_get_inventory_url` auto-use fixture fails the test on any
  path the server didn't recognise, so a missing entry can't silently become empty data.
- The `api` fixture is the whole rendered API (`asyncio.run(build_api(...))`); route tests assign it to
  `app.state.api`. `build_cmdb` runs the async `refresh()` from a sync test for tests of `AnsibleCMDB` itself.
  There is no pytest-asyncio.
- The `client` fixture does **not** enter the TestClient context, so the lifespan and its refresh task don't run.
  `test_lifespan_builds_api` covers the lifespan and waits for the build before leaving the context.
- The SPA fallback test monkeypatches `ansibleinventorycmdb.app.FRONTEND_DIR` to a temp dir, so pytest needs no
  `pnpm build`.
- Always pass `tmp_path` as `instance_path` to `create_app`: with none, `load_config()` writes its default
  config into your real `instance/`. `AnsibleCMDB` takes no path and writes nothing, so it needs no tmp dir.
- Test configs live in [`tests/configs/`](tests/configs/); test inventories in [`tests/inventories/`](tests/inventories/).

## Code Conventions

- **Type hints** required on all functions; enforced by ruff (`ANN` rules, relaxed in tests).
- **Google-style docstrings** required on all modules, classes, and public functions.
- **Double quotes**, max line length **120**.
- `ruff` is configured with `select = ["ALL"]` and selective ignores — run `ruff check` before committing.
- Module logger: `logger = logging.getLogger(__name__)` at module level. `setup_logger` configures the root
  logger, so every module inherits it; there is no wrapper to go through and no custom TRACE level.
- TypeScript: `strict`, single quotes and no semicolons (biome), camelCase. Fields read off the API keep its
  snake_case.
