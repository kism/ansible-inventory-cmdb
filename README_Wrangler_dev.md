# Working on the Worker

Local development, project layout and the sharp edges you only hit while changing things. To deploy, see
[README_Wrangler.md](README_Wrangler.md).

## Run it locally

```bash
npm run dev
curl http://localhost:8787/cdn-cgi/handler/scheduled   # cron triggers don't fire in dev
```

`npm run dev` preflights that `src/config.yml` is a symlink that resolves, the same as `deploy` does — a missing
or dangling link is bundled as nothing at all, and the Worker then dies on import with
`FileNotFoundError: /session/metadata/config.yml`. Calling `pywrangler` directly skips that check.

The R2 binding is local by default, so a dev build writes to a simulated bucket and touches nothing real. To aim
[`scripts/build-token.sh`](scripts/build-token.sh) at the dev server, override `WORKER_URL` — the environment
wins over `.dev.vars`:

```bash
WORKER_URL=http://localhost:8787 scripts/build-token.sh run
```

To seed the *real* bucket from a local run, temporarily add `"remote": true` to the R2 binding in
`wrangler.jsonc`. Take it back out afterwards — left in, every local dev run overwrites production.

## Don't bump `compatibility_date` casually

A date of **2026-08-05 or later** makes Cloudflare reject the deploy:

```
Uncaught Error: Dynamic require of "fs" is not supported ... in loadPyodide [code: 10021]
```

Pyodide fails to boot during Cloudflare's deploy-time validation. This reproduces on a zero-dependency
hello-world Python Worker, so it is a platform bug rather than anything in this project. `2026-08-01` is the
newest date that deploys; re-test the boundary before raising it.

A date newer than the workerd binary the pinned wrangler ships with stops `npm run dev` from starting at all, so
bumping wrangler and bumping this tend to go together.

## Layout

| Path                               | Role                                                            |
| ---------------------------------- | --------------------------------------------------------------- |
| [`src/entry.py`](src/entry.py)     | `scheduled` (cron) and `fetch` (ad-hoc, token-guarded) handlers |
| `src/config.yml`                   | Symlink to `instance/config.yml`, bundled with the Worker       |
| [`wrangler.jsonc`](wrangler.jsonc) | Cron schedule, R2 binding, module rules                         |
| [`pyproject.toml`](pyproject.toml) | One project for all three run modes, see below                  |
| [`package.json`](package.json)     | Pins wrangler, and defines every `npm run` script               |

`src/entry.py` sits beside `src/ansibleinventorycmdb/` on purpose. wrangler bundles everything under the
entrypoint's directory, so the package ships at the same path the entrypoint imports it from, with no copying,
symlinking or path dependency involved.

Non-`.py` files only make it into the bundle if a `rules` entry in `wrangler.jsonc` matches them — that is what
carries the templates, CSS, fonts and `src/config.yml`. Add a new file type without one and it goes missing
silently.

## The dependency list is the Worker's install list

`pywrangler` reads **`[project.dependencies]` and nothing else** — extras and dependency-groups are invisible to
it — and resolves that list against the Pyodide package index with `--no-build`. So:

| Where                                    | What                            | How to install              |
| ---------------------------------------- | ------------------------------- | --------------------------- |
| `[project.dependencies]`                 | httpx, jinja2, pydantic, pyyaml | `uv sync` — Worker + CLI    |
| `[project.optional-dependencies].server` | fastapi, uvicorn                | `uv sync --extra server`    |
| `[dependency-groups].worker`             | workers-py, workers-runtime-sdk | `uv sync` (a default group) |

Anything you add to the first row must have a Pyodide wheel, or `npm run dev`/`deploy` fails at the resolve step.
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
