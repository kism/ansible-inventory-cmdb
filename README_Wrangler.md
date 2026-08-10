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

A deployed cron trigger **cannot** be fired on demand — `wrangler dev --remote` doesn't dispatch scheduled
events either — so the Worker also has a `fetch` handler for ad-hoc builds. See below.

## Run a build on demand

Set a `BUILD_TOKEN` secret once, then `POST`/`GET` the Worker's URL with it as a bearer token:

```bash
cd worker
npx wrangler secret put BUILD_TOKEN          # paste a long random string, keep a copy
uv run pywrangler deploy
curl -H "Authorization: Bearer $BUILD_TOKEN" https://<your-worker>.workers.dev
# -> Wrote 55 objects
```

That's also how you get the site populated immediately after the first deploy, rather than waiting for 14:00 UTC.

**Deploying never runs the cron.** A fresh deploy leaves the bucket empty until the next scheduled fire, so the
public URL 404s until then. Either use the endpoint above, or seed the bucket from a local run by temporarily
adding `"remote": true` to the R2 binding in `wrangler.jsonc`:

```bash
uv run pywrangler dev                                   # binding now points at the real bucket
curl http://localhost:8787/cdn-cgi/handler/scheduled
```

Take `"remote": true` back out afterwards — left in, every local dev run overwrites production.

## Checking the last run

`wrangler` has no historical log query; `npx wrangler tail ansible-inventory-cmdb --format pretty` only streams
what happens while you're attached.

To find out when the site was last rebuilt, ask the site — every run rewrites all 55 objects:

```bash
curl -sI https://<your-domain>/index.html | grep -i last-modified
```

Don't use `wrangler r2 bucket info` for this. Its `object_count` is a lagging metric and still read `0` several
minutes after a run had demonstrably written all 55 objects.

The endpoint **fails closed**: with no `BUILD_TOKEN` set, every request gets a 404 and no build runs. The guard
matters because the `workers.dev` URL is public and each build costs ~75 requests against whatever hosts your
inventory — an open endpoint would be a free way for anyone to hammer that server. A wrong or missing token
returns 404 rather than 403, so it doesn't advertise itself.

For local `pywrangler dev`, put the token in `worker/.dev.vars` (gitignored):

```bash
echo 'BUILD_TOKEN="whatever-you-like"' > .dev.vars
```

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
| [`worker/src/entry.py`](worker/src/entry.py)     | `scheduled` (cron) and `fetch` (ad-hoc, token-guarded) handlers   |
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
