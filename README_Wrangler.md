# Run as a Cloudflare Worker

An alternate run mode to the [web app](README.md): instead of a server, a cron-triggered Python Worker builds the
CMDB once a day and writes every page into an R2 bucket, which serves them as static files. Same code, same
templates — see [`site.py`](src/ansibleinventorycmdb/site.py), which the web app and the Worker both render
through.

Requires **Workers Paid**. Building the real inventory takes ~75 subrequests (one per host and group var file,
times two paths), over the free plan's cap of 50.

## Prerequisites

`wrangler` is pinned in [`worker/package.json`](worker/package.json) rather than installed globally, so it does
not need to be on your PATH:

```bash
cd worker
npm install
```

`pywrangler` shells out to `npx wrangler`, which picks up this local copy instead of downloading one.

## Deploy

```bash
cd worker
npx wrangler login --browser false
npx wrangler r2 bucket create ansible-inventory-cmdb   # then enable public access on it in the dashboard
$EDITOR src/config.yml                                 # same schema as instance/config.yml
uv run pywrangler dev                                  # then trigger a build, see below
uv run pywrangler deploy
```

`npm run dev` and `npm run deploy` are shorthands for the last two.

Cron Triggers don't fire during local development, so trigger a build by hand:

```bash
curl http://localhost:8787/cdn-cgi/handler/scheduled
```

There is no equivalent for a deployed Worker — a cron trigger can't be fired on demand — so the first real build
happens at the next 14:00 UTC.

### Don't bump `compatibility_date` casually

A date of **2026-08-05 or later** makes Cloudflare reject the deploy:

```
Uncaught Error: Dynamic require of "fs" is not supported ... in loadPyodide [code: 10021]
```

Pyodide fails to boot during Cloudflare's deploy-time validation. This reproduces on a zero-dependency
hello-world Python Worker, so it is a platform bug rather than anything in this project. `2026-08-01` is the
newest date that deploys; re-test the boundary before raising it.

## URLs

The bucket has no index document, so the site's entry point is **`/index.html`**, not `/`. Every page is written
as `<path>/index.html` and linked that way. If you put a custom domain in front of the bucket, a redirect rule
from `/` to `/index.html` tidies that up.

## Render to a directory instead

The same site, without Cloudflare in the picture:

```bash
uv run ansibleinventorycmdb-generate ./out
```

## Layout

| Path                                             | Role                                                             |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| [`worker/src/entry.py`](worker/src/entry.py)     | The `scheduled` handler: build the CMDB, PUT every page to R2    |
| [`worker/src/config.yml`](worker/src/config.yml) | The inventories to render, bundled with the Worker               |
| [`worker/wrangler.jsonc`](worker/wrangler.jsonc) | Cron schedule, R2 binding, module rules, and the copy build step |
| [`worker/pyproject.toml`](worker/pyproject.toml) | A separate uv project, resolved against the Pyodide index        |
| [`worker/package.json`](worker/package.json)     | Pins wrangler, so no global install is needed                    |

## Generated directories

Two directories in `worker/` are build artifacts. Both are gitignored and both refresh themselves — there is
nothing to run by hand:

| Path                              | Made by                                 | Refreshed when                                                           |
| --------------------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| `worker/src/ansibleinventorycmdb` | the `build` command in `wrangler.jsonc` | every `dev` and `deploy` — it's an `rm -rf` + `cp -r`                    |
| `worker/python_modules`           | `pywrangler`, from `pylock.toml`        | when `pyproject.toml` or `pylock.toml` is newer than its `.synced` token |

The package is copied rather than depended on because `pywrangler` resolves against the Pyodide package index with
`--no-build`, so a path dependency fails to resolve, and wrangler does not follow symlinks.

**The one thing that does not maintain itself** is the dependency list in `worker/pyproject.toml`, which repeats
the package's runtime dependencies by hand. `tests/test_worker_deps.py` fails if the two drift, because otherwise
a missing dependency only shows up as a Worker that dies on import at 14:00 UTC.
