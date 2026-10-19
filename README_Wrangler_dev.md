# Working on the Worker

Local development, project layout and the sharp edges you only hit while changing things. To deploy, see
[README_Wrangler.md](README_Wrangler.md).

## Run it locally

```bash
pnpm dev:cf
curl http://localhost:8787/cdn-cgi/handler/scheduled   # cron triggers don't fire in dev
```

`pnpm dev:cf` builds the frontend first (wrangler's `build.command` runs vite in `cloudflare` mode) and serves it on the same
port. That is the Cloudflare build, so it reads the *real* API at cmdb-api.kierangee.au, not the local simulated
bucket. To look at the pages a local build produced, use the web app; both build through the same `api.py`.

`pnpm check_worker` is the same thing without the babysitting: it starts the dev server, waits for an
untokened `/refresh` to answer 404, for `/status` to return its JSON and for the frontend to be served from
assets, then shuts it down. That covers the ways the Worker breaks without pytest noticing — a dependency that
won't resolve against the Pyodide index, a bundle that won't import under wasm, and assets that aren't wired up —
so it runs in CI and in `pnpm check`.

The R2 binding is local by default, so a dev build writes to a simulated bucket and touches nothing real. The
dev server reads `BUILD_TOKEN` from `.dev.vars`, which `pnpm provision` wrote, so `/refresh` works there too:

```bash
curl -X POST -H "Authorization: Bearer $(sed -n 's/^BUILD_TOKEN="\(.*\)"/\1/p' .dev.vars)" localhost:8787/refresh
```

To seed the *real* bucket from a local run, temporarily add `"remote": true` to the R2 binding in
`wrangler.jsonc`. Take it back out afterwards — left in, every local dev run overwrites production.

## Don't change `compatibility_date` casually

The date picks the Python version the edge runs — pywrangler's `metadata.py` maps it, and **2026-09-08 or later
means Python 3.14**. Below that you get the 3.13 runtime, which never puts the bundled `python_modules` on
`sys.path`, so the deploy is rejected:

```
File "/session/metadata/entry.py", line 18, in <module>
  import yaml
ModuleNotFoundError: No module named 'yaml' [code: 10021]
```

`pnpm dev:cf` boots that same bundle without complaint, so local success proves nothing here. The ceiling is the
workerd binary wrangler ships with: a date newer than that and `pnpm dev:cf` refuses to start.

The date also decides which Pyodide index the vendored wheels come from, so after changing it:

```bash
rm pylock.toml              # it pins the previous runtime's wheels
uv run pywrangler sync --force
pnpm check_worker
```

## Layout

| Path                               | Role                                                            |
| ---------------------------------- | --------------------------------------------------------------- |
| [`src/entry.py`](src/entry.py)     | `scheduled` (cron) and `fetch` (ad-hoc, token-guarded) handlers |
| [`src/config.yml`](src/config.yml) | The Worker's config, tracked and bundled with it                |
| [`wrangler.jsonc`](wrangler.jsonc) | Cron, R2 binding, module rules, assets, the frontend's domain   |
| [`frontend/`](frontend/)           | The TypeScript frontend, the Worker's static assets once built  |
| [`frontend/.env.cloudflare`](frontend/.env.cloudflare) | The API's URL, baked into the Cloudflare build |
| [`pyproject.toml`](pyproject.toml) | One project for both hosts, see below                           |
| [`package.json`](package.json)     | Pins wrangler, vite and typescript, and defines every pnpm script |
| [`scripts/provision.sh`](scripts/provision.sh) | `pnpm provision`: bucket, CORS, API domain, `BUILD_TOKEN` |

`src/entry.py` sits beside `src/ansibleinventorycmdb/` on purpose. wrangler bundles everything under the
entrypoint's directory, so the package ships at the same path the entrypoint imports it from, with no copying,
symlinking or path dependency involved.

## The dependency list is the Worker's install list

`pywrangler` reads **`[project.dependencies]` and nothing else** — extras and dependency-groups are invisible to
it — and resolves that list against the Pyodide package index with `--no-build`. So:

| Where                                    | What                            | How to install              |
| ---------------------------------------- | ------------------------------- | --------------------------- |
| `[project.dependencies]`                 | httpx, pydantic, pyyaml         | `uv sync` — the Worker      |
| `[project.optional-dependencies].server` | fastapi, uvicorn                | `uv sync --extra server`    |
| `[dependency-groups].worker`             | workers-py, workers-runtime-sdk | `uv sync` (a default group) |

Anything you add to the first row must have a Pyodide wheel, or `pnpm dev:cf`/`deploy` fails at the resolve step.
Notably **aiohttp does not**: recent versions have no wasm wheel at all, and older ones resolve to the
socket-based build, which dies under Pyodide with `RuntimeError("SSL is not supported.")`. Pyodide ships its own
patched `httpx` that goes through the JS `fetch` API, which is why that's the client here.

## Generated files

All gitignored, all self-maintaining — there is nothing to run by hand:

| Path              | Made by                             | Refreshed when                                                          |
| ----------------- | ----------------------------------- | ----------------------------------------------------------------------- |
| `python_modules/` | `pywrangler`, from `pylock.toml`    | when `pyproject.toml` or `pylock.toml` is newer than its `.synced` token |
| `pylock.toml`     | `pywrangler`, from `pyproject.toml` | on sync; it then constrains later resolves so versions don't drift       |
| `.venv-workers/`  | `pywrangler`                        | alongside `python_modules`, for editor/type support                      |
| `frontend/dist/`  | vite, via `build.command`           | before every `pnpm dev:cf`/deploy bundle                                   |
