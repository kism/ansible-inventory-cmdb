# Deploy as a Cloudflare Worker

The other host, next to the [web app](README.md): instead of a server, a cron-triggered Python Worker builds the
CMDB's JSON API once a day and writes it into an R2 bucket, which serves it at **cmdb-api.kierangee.au**. The
frontend is the same Worker's static assets, at **cmdb.kierangee.au**, and renders every page in the browser
from the bucket. Same API as the web app — both build it through [`api.py`](src/ansibleinventorycmdb/api.py) —
and the same frontend build, pointed at the bucket's domain instead of `/api`. A page view never runs the Python.

This file is the deployment guide. For local development, the project layout and how the dependency list works,
see [README_Wrangler_dev.md](README_Wrangler_dev.md).

Runs on the **free plan**. A build probes every host and group at two paths — ~80 URLs for the real inventory,
well over the free plan's cap of 50 external subrequests — so GitHub-hosted inventories are served out of one
repo zip per build instead. See `github_zip_fetcher` in [`cmdb.py`](src/ansibleinventorycmdb/cmdb.py).

## Deploy

**This deploys [cmdb.kierangee.au](https://cmdb.kierangee.au) and cmdb-api.kierangee.au.** The deployment is
config in the repo, not parameters you pass in — [`src/config.yml`](src/config.yml) holds the inventories,
[`wrangler.jsonc`](wrangler.jsonc) the Worker and bucket names, cron and the frontend's domain, and
[`frontend/.env.cloudflare`](frontend/.env.cloudflare) the API's URL. To run your own, fork it and change those;
`wrangler.jsonc`'s comments name them.

It deploys from Cloudflare's git integration, Workers Builds. What that can't do — create the bucket, give it a
domain and a CORS policy, set the `/refresh` token — [`scripts/provision.sh`](scripts/provision.sh) does, once,
reading every name off the files above:

```bash
uv sync
nvm install                          # node 26, from .nvmrc
pnpm install
$EDITOR src/config.yml wrangler.jsonc frontend/.env.cloudflare   # if this is a fork
pnpm provision                       # login, bucket, CORS, API domain, BUILD_TOKEN; safe to re-run
```

It asks for the API domain's zone ID (on the domain's dashboard overview page) unless `CF_ZONE_ID` is set.
Skipping the API's custom domain works too: enable the bucket's `r2.dev` development URL, put that in
`frontend/.env.cloudflare`, and provision skips the domain step. It finishes by printing the next two steps:
connecting the repo, and the URL that triggers the first build.

`src/config.yml` is bundled with the Worker because a Worker has no instance path to read a config from at
runtime, and `wrangler.jsonc`'s `Data` rules carry `*.yml` into the bundle. It is tracked rather than gitignored
for the same reason: a checkout with no config produces a bundle that dies on import with
`FileNotFoundError: /session/metadata/config.yml`. It is not secret — the whole site it renders is public.

### Connecting the repo

**Workers & Pages → the Worker → Settings → Build**, connect the repo, and set both commands, because the
defaults don't work here:

| Setting        | Value             |
| -------------- | ----------------- |
| Build command  | `pipx install uv` |
| Deploy command | `pnpm run deploy` |

Every push to `main` then deploys; other branches get preview URLs. The build image has no `uv`, hence the build
command; wrangler's own `build.command` then vendors the Python packages (`pywrangler sync`) and builds the
frontend before every bundle. If `python_modules/` is ever missing, wrangler uploads a bundle with **no vendored
packages at all** rather than erroring, and the deploy is rejected with `ModuleNotFoundError: No module named
'yaml'` — `entry.py`'s first vendored import. The tell is `Total Upload`: a few hundred KiB instead of ~8 MB.
`pnpm run deploy` rather than the stock `npx wrangler deploy` because it passes the commit sha the footer shows.

## Running a build

The cron trigger fires daily at 14:00 UTC. **Nothing else fires it**: deploying doesn't, and a deployed cron
trigger cannot be dispatched by hand — `wrangler dev --remote` returns error 1042 rather than sending one. That
is why the Worker also answers `/refresh`, token-guarded, and why a fresh deploy leaves the bucket 404ing — and
the frontend saying it couldn't load the CMDB — until you use it. `pnpm provision` prints both forms:

```bash
curl -X POST -H "Authorization: Bearer <token>" https://<frontend domain>/refresh
```

The token is `BUILD_TOKEN` in `.dev.vars` (gitignored, `umask 077`), the **only** copy — `wrangler secret list`
returns names, never values, so one that lives only on Cloudflare can't be read back. Re-running provision reuses
it; to rotate it, delete the line and re-run.

### Triggering it without a terminal

**The Cloudflare dashboard cannot fire a cron trigger.** There is no "run now" button; _Settings → Trigger
Events_ only lists past runs. The one thing you can click is a URL, so the token is accepted as `?token=` as well
as a bearer header — `pnpm provision` prints the whole thing to bookmark.

The trade is that the token then sits in your browser history and Cloudflare's request logs. To avoid that, use
the header form, or put the Worker on a custom domain behind
[Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/) and drop the token.

The guard itself is not optional. The `workers.dev` URL is public and each build pulls a whole repo down from
whoever hosts your inventory, so an open endpoint is a free way for anyone to hammer that server. It **fails
closed** — no `BUILD_TOKEN`, no way in — and a wrong token gets a 404 rather than a 403, the same answer as any
path that isn't `/refresh` or `/status`, so nothing advertises itself.

## Checking the last run

Run logs are in the dashboard (observability is on). For a yes/no, the Worker
answers `/status` — no token needed, it only reports what a public bucket already shows:

```bash
curl https://<frontend domain>/status
{"ok": true, "last_build": "2026-08-17T01:50:40.144000+00:00", "age_seconds": 1, "stale_after_seconds": 93600}
```

It reads the upload time of `inventories.json`, which every run rewrites, so there is nothing to keep in sync and
one Cloudflare-internal request to answer with. A failed run writes nothing, so it shows up as an age that keeps
climbing rather than as an error message. Past 26 hours — a daily cron plus slack — `ok` goes false and the
status code is **503**, so an uptime monitor can watch the URL without parsing anything. The web app's `/status`
returns the same body.

Same answer straight from the API, if you'd rather not involve the Worker:

```bash
curl -sI https://cmdb-api.kierangee.au/inventories.json | grep -i last-modified
```

Don't use `wrangler r2 bucket info` for this. Its `object_count` is a lagging metric and still read `0` several
minutes after a run had demonstrably written every object.

## Domains

| Domain                | Serves                     | Set up by                                             |
| --------------------- | -------------------------- | ----------------------------------------------------- |
| cmdb.kierangee.au     | the frontend, `/refresh`, `/status` | `routes` in `wrangler.jsonc`, on deploy |
| cmdb-api.kierangee.au | the API, straight out of R2 | `pnpm provision`, along with its CORS policy |

The API's keys all end in `.json` (`inventories.json`, `inventory/<name>/host/<host>.json`, ...), so R2 serves
every one of them as is: no index document, no rewrite rule. The frontend is a single-page app, and the Worker's
assets hand `index.html` to any navigation that isn't a file, so a reload on `/inventory/<name>/host/<host>`
works. `/refresh` and `/status` are listed in `run_worker_first`, so they still reach the Worker.

Every build also deletes whatever is in the bucket that the build didn't write, so a host dropped from the
inventory disappears from the API rather than lingering.
