# Run as a Cloudflare Worker

An alternate run mode to the [web app](README.md): instead of a server, a cron-triggered Python Worker builds the
CMDB once a day and writes every page into an R2 bucket, which serves them as static files. Same code, same
templates — see [`site.py`](src/ansibleinventorycmdb/site.py), which the web app and the Worker both render
through.

Requires **Workers Paid**. Building the real inventory takes ~75 subrequests (one per host and group var file,
times two paths), over the free plan's cap of 50.

## Prerequisites

`wrangler` is pinned in [`package.json`](package.json) rather than installed globally, so it does not need to be on
your PATH:

```bash
uv sync
npm install
```

`pywrangler` shells out to `npx wrangler`, which picks up this local copy instead of downloading one. Every command
below runs from the repo root — there is one `pyproject.toml` and pywrangler insists on finding `wrangler.jsonc`
beside it.

## Deploy

```bash
npx wrangler login --browser false
npx wrangler r2 bucket create ansible-inventory-cmdb   # then enable public access on it in the dashboard
$EDITOR instance/config.yml                            # src/config.yml is a symlink to it
npm run dev                                            # then trigger a build, see below
npm run deploy
```

`npm run dev` and `npm run deploy` are the same two commands with a preflight check that `src/config.yml`
is a symlink that resolves. Prefer them: a missing or dangling link is bundled as nothing at all, and the
Worker then dies on import with `FileNotFoundError: /session/metadata/config.yml`.

Cron Triggers don't fire during local development, so trigger a build by hand:

```bash
curl http://localhost:8787/cdn-cgi/handler/scheduled
```

A deployed cron trigger **cannot** be fired on demand — `wrangler dev --remote` doesn't dispatch scheduled
events either — so the Worker also has a `fetch` handler for ad-hoc builds. See below.

## Run a build on demand

Set a `BUILD_TOKEN` secret once, then `POST`/`GET` the Worker's URL with it as a bearer token:

```bash
npx wrangler secret put BUILD_TOKEN          # paste a long random string, keep a copy
uv run pywrangler deploy
curl -H "Authorization: Bearer $BUILD_TOKEN" https://<your-worker>.workers.dev
# -> Wrote 55 objects
```

That's also how you get the site populated immediately after the first deploy, rather than waiting for 14:00 UTC.

[`scripts/build-token.sh`](scripts/build-token.sh) wraps all of that:

```bash
scripts/build-token.sh set     # generate a token, store it, upload it to Cloudflare
scripts/build-token.sh run     # trigger a build on the deployed Worker
scripts/build-token.sh get     # print the token
scripts/build-token.sh url     # print the bookmarkable trigger URL
```

It keeps the token in `.dev.vars` (gitignored, `chmod 600`), which is the *only* copy — `wrangler secret list`
returns names, never values, so a token that only exists on Cloudflare cannot be read back. Lost it? `set` a new
one. The workers.dev subdomain is account-specific and no wrangler command reports it, so `run` and `url` want
it in the same file:

```bash
WORKER_URL="https://<your-worker>.workers.dev"
```

`WORKER_URL` from the environment wins over the file, which is how you point `run` at a dev server:
`WORKER_URL=http://localhost:8787 scripts/build-token.sh run`.

### Triggering it without a terminal

**The Cloudflare dashboard cannot fire a cron trigger.** There is no "run now" button; *Settings → Trigger
Events* only lists past runs, and `/cdn-cgi/handler/scheduled` works in `wrangler dev` alone. The one thing you
can click is a URL, so the same token is also accepted as `?token=`:

```
https://<your-worker>.workers.dev/?token=<BUILD_TOKEN>
```

Bookmark that and a build is one click, from anything with a browser. Same constant-time comparison, same
fail-closed 404 — the only difference is that the token is now in a URL, so it lands in your browser history and
Cloudflare's own request logs. That's the trade for a clickable trigger; if you'd rather it not be, use the
header form, or put the Worker on a custom domain behind [Cloudflare
Access](https://developers.cloudflare.com/cloudflare-one/access-controls/) and drop the token entirely.

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

For local `pywrangler dev`, put the token in `.dev.vars` (gitignored):

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

R2 public buckets have no index document, so the site's entry point is **`/index.html`**, not `/`. Every page is
written as `<path>/index.html` and linked that way. Bare `/` and `/inventory/x/` have no object key behind them
and 404.

A **URL Rewrite** on the zone in front of the bucket fixes that. Not a redirect — a rewrite is resolved at the
edge, so the address bar keeps the clean path — and not anything in `wrangler.jsonc`: the Worker only *writes*
objects on its cron trigger, and requests to the bucket's domain are served straight from R2 without ever
reaching it. Transform rules are zone config, so this does **not** travel with `npm run deploy`; a new bucket or
domain needs it set up again by hand.

In the dashboard, on the zone that owns the domain, **Rules → Overview → Create rule → URL Rewrite Rule**:

| Field                    | Value                                                              |
| ------------------------ | ------------------------------------------------------------------ |
| Custom filter expression | `(http.host eq "<your-domain>" and ends_with(http.request.uri.path, "/"))` |
| Path → Rewrite to        | **Dynamic**, `concat(http.request.uri.path, "index.html")`         |

Leave *Query* alone. The same thing through the API:

```bash
curl "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/rulesets/phases/http_request_transform/entrypoint" \
  --request PUT \
  --header "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  --json '{
    "rules": [{
      "expression": "(http.host eq \"<your-domain>\" and ends_with(http.request.uri.path, \"/\"))",
      "description": "CMDB bucket: serve index.html for directory paths",
      "action": "rewrite",
      "action_parameters": {
        "uri": { "path": { "expression": "concat(http.request.uri.path, \"index.html\")" } }
      }
    }]
  }'
```

That `PUT` **replaces every rule in the zone's `http_request_transform` phase**, so if the zone already has URL
rewrites, use the dashboard, or `GET` the entrypoint first and re-`PUT` the existing rules alongside this one.

Matching on a trailing slash is deliberate. A path with neither a slash nor an extension —
`/inventory/kism_main` — still 404s; catching those would mean rewriting every extensionless path, which starts
guessing at things like `/static/`. Nothing links that way, so it is left alone.

Check it with `curl -sI`: a rewrite returns `200` with **no** `location:` header, where a redirect would return
`301`.

## Render to a directory instead

The same site, without Cloudflare in the picture:

```bash
uv run ansibleinventorycmdb-generate ./out
```

## Layout

| Path                                   | Role                                                           |
| -------------------------------------- | -------------------------------------------------------------- |
| [`src/entry.py`](src/entry.py)         | `scheduled` (cron) and `fetch` (ad-hoc, token-guarded) handlers |
| `src/config.yml`                       | Symlink to `instance/config.yml`, bundled with the Worker       |
| [`wrangler.jsonc`](wrangler.jsonc)     | Cron schedule, R2 binding, module rules                        |
| [`pyproject.toml`](pyproject.toml)     | One project for all three run modes, see below                 |
| [`package.json`](package.json)         | Pins wrangler, so no global install is needed                  |

`src/entry.py` sits beside `src/ansibleinventorycmdb/` on purpose. wrangler bundles everything under the
entrypoint's directory, so the package ships at the same path the entrypoint imports it from, with no copying,
symlinking or path dependency involved.

## The dependency list is the Worker's install list

`pywrangler` reads **`[project.dependencies]` and nothing else** — extras and dependency-groups are invisible to it
— and resolves that list against the Pyodide package index with `--no-build`. So:

| Where                                    | What                            | How to install               |
| ---------------------------------------- | ------------------------------- | ---------------------------- |
| `[project.dependencies]`                 | httpx, jinja2, pydantic, pyyaml | `uv sync` — Worker + CLI     |
| `[project.optional-dependencies].server` | fastapi, uvicorn                | `uv sync --extra server`     |
| `[dependency-groups].worker`             | workers-py, workers-runtime-sdk | `uv sync` (a default group)  |

Anything you add to the first row must have a Pyodide wheel, or `pywrangler dev`/`deploy` fails at the resolve
step. Notably **aiohttp does not**: recent versions have no wasm wheel at all, and older ones resolve to the
socket-based build, which dies under Pyodide with `RuntimeError("SSL is not supported.")`. Pyodide ships its own
patched `httpx` that goes through the JS `fetch` API, which is why that's the client here.

## Generated files

All gitignored, all self-maintaining — there is nothing to run by hand:

| Path              | Made by                          | Refreshed when                                                           |
| ----------------- | -------------------------------- | ------------------------------------------------------------------------ |
| `python_modules/` | `pywrangler`, from `pylock.toml` | when `pyproject.toml` or `pylock.toml` is newer than its `.synced` token |
| `pylock.toml`     | `pywrangler`, from `pyproject.toml` | on sync; it then constrains later resolves so versions don't drift    |
| `.venv-workers/`  | `pywrangler`                     | alongside `python_modules`, for editor/type support                      |
