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
[`wrangler.jsonc`](wrangler.jsonc) the bucket, cron and the frontend's domain,
[`frontend/.env.cloudflare`](frontend/.env.cloudflare) the API's URL, and `package.json`'s `domain` and `cors`
scripts the API's domain. To run your own, fork it and change those; `wrangler.jsonc`'s comments name them.

Every Cloudflare command is a pnpm script in [`package.json`](package.json), so there is nothing to install
globally and nothing to remember about flags. `deploy` and `login` share their names with pnpm built-ins, so they
need the `run`: `pnpm run deploy`, not `pnpm deploy`. Run them from the repo root — there is one `pyproject.toml`, and
pywrangler insists on finding `wrangler.jsonc` beside it.

```bash
uv sync
nvm install                          # node 26, from .nvmrc
pnpm install
pnpm run login
pnpm bucket                          # create the R2 bucket
CF_ZONE_ID=<zone id> pnpm domain     # put it on cmdb-api.kierangee.au, see Domains below
pnpm cors                            # let the frontend read it from another origin
$EDITOR src/config.yml               # your inventories, if this is a fork
pnpm run deploy                      # builds the frontend, and puts the Worker on cmdb.kierangee.au
./scripts/build-token.sh set         # the on-demand build endpoint, see below
./scripts/build-token.sh run         # seed the bucket now, rather than waiting for 14:00 UTC
```

The zone ID is on the domain's dashboard overview page. Skipping the API's custom domain works too: enable the
bucket's `r2.dev` development URL and put that in `frontend/.env.cloudflare` instead.

`src/config.yml` is bundled with the Worker because a Worker has no instance path to read a config from at
runtime, and `wrangler.jsonc`'s `Data` rules carry `*.yml` into the bundle. It is tracked rather than gitignored
for the same reason: a checkout with no config produces a bundle that dies on import with
`FileNotFoundError: /session/metadata/config.yml`. It is not secret — the whole site it renders is public.

### Deploying from Workers Builds

Connecting the repo to Workers Builds (Cloudflare's git integration) needs both commands set, because the
defaults don't work here:

| Setting        | Value             |
| -------------- | ----------------- |
| Build command  | `pipx install uv` |
| Deploy command | `pnpm run deploy` |

`python_modules/` is gitignored — `pywrangler sync` writes it, and `pnpm run deploy` goes through pywrangler,
which syncs first. The stock deploy command `npx wrangler deploy` skips that step, so on a fresh checkout it
uploads a bundle with **no vendored packages at all** and the deploy is rejected at validation with
`ModuleNotFoundError: No module named 'yaml'` — `entry.py`'s first vendored import. Nothing warns you: the
missing `python_modules/` is a debug-level log line, and the only visible symptom is `Total Upload` being a few
hundred KiB instead of ~8 MB. The build image has no `uv`, hence the build command. The frontend needs nothing
extra: wrangler's own `build.command` runs `pnpm build:cf` before every bundle.

## Running a build

The cron trigger fires daily at 14:00 UTC. **Nothing else fires it**: deploying doesn't, and a deployed cron
trigger cannot be dispatched by hand — `wrangler dev --remote` returns error 1042 rather than sending one. That
is why the Worker also answers `/refresh`, token-guarded, and why a fresh deploy leaves the bucket 404ing — and
the frontend saying it couldn't load the CMDB — until you use it.

[`scripts/build-token.sh`](scripts/build-token.sh) is that endpoint's front end:

```bash
scripts/build-token.sh set     # generate a token, store it, upload it to Cloudflare
scripts/build-token.sh run     # trigger a build on the deployed Worker
scripts/build-token.sh url     # print the bookmarkable trigger URL, token included
```

It keeps the token in `.dev.vars` (gitignored, `umask 077`), the **only** copy — `wrangler secret list` returns
names, never values, so one that lives only on Cloudflare can't be read back. Lost it? `set` a new one. Add the
workers.dev subdomain to the same file, since no wrangler command reports it:

```bash
WORKER_URL="https://<your-worker>.workers.dev"
```

### Triggering it without a terminal

**The Cloudflare dashboard cannot fire a cron trigger.** There is no "run now" button; _Settings → Trigger
Events_ only lists past runs. The one thing you can click is a URL, so the token is accepted as `?token=` as well
as a bearer header — `scripts/build-token.sh url` prints the whole thing to bookmark.

The trade is that the token then sits in your browser history and Cloudflare's request logs. To avoid that, use
the header form, or put the Worker on a custom domain behind
[Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/) and drop the token.

The guard itself is not optional. The `workers.dev` URL is public and each build pulls a whole repo down from
whoever hosts your inventory, so an open endpoint is a free way for anyone to hammer that server. It **fails
closed** — no `BUILD_TOKEN`, no way in — and a wrong token gets a 404 rather than a 403, the same answer as any
path that isn't `/refresh` or `/status`, so nothing advertises itself.

## Checking the last run

`pnpm tail` only streams what happens while you're attached; wrangler has no historical log query. The Worker
answers `/status` instead — no token needed, it only reports what a public bucket already shows:

```bash
curl https://<worker>.workers.dev/status
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
| cmdb.kierangee.au     | the frontend, `/refresh`, `/status` | `routes` in `wrangler.jsonc`, on `pnpm run deploy` |
| cmdb-api.kierangee.au | the API, straight out of R2 | `pnpm domain` once, and `pnpm cors` for its CORS policy |

The API's keys all end in `.json` (`inventories.json`, `inventory/<name>/host/<host>.json`, ...), so R2 serves
every one of them as is: no index document, no rewrite rule. The frontend is a single-page app, and the Worker's
assets hand `index.html` to any navigation that isn't a file, so a reload on `/inventory/<name>/host/<host>`
works. `/refresh` and `/status` are listed in `run_worker_first`, so they still reach the Worker.

Every build also deletes whatever is in the bucket that the build didn't write, so a host dropped from the
inventory disappears from the API rather than lingering.

### Moving from the old HTML site

The bucket used to hold rendered HTML and sit on cmdb.kierangee.au itself, behind a zone URL Rewrite appending
`index.html`. Once, in this order:

1. Free the hostname: **R2 → ansible-inventory-cmdb → Settings → Custom Domains**, remove cmdb.kierangee.au. The
   site is down from here until step 4.
2. Delete the URL Rewrite rule (**Rules → Overview** in the zone's dashboard). Nothing needs it any more.
3. `CF_ZONE_ID=<zone id> pnpm domain`, which now adds cmdb-api.kierangee.au, then `pnpm cors`.
4. `pnpm run deploy`, which attaches cmdb.kierangee.au to the Worker.
5. `scripts/build-token.sh run`. The first JSON build also deletes the old HTML objects.

Old bookmarks of the form `/inventory/<name>/index.html` still land on the right page.
