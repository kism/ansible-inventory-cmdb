# Deploy as a Cloudflare Worker

An alternate run mode to the [web app](README.md): instead of a server, a cron-triggered Python Worker builds the
CMDB once a day and writes every page into an R2 bucket, which serves them as static files. Same code, same
templates — see [`site.py`](src/ansibleinventorycmdb/site.py), which both modes render through.

This file is the deployment guide. For local development, the project layout and how the dependency list works,
see [README_Wrangler_dev.md](README_Wrangler_dev.md).

Requires **Workers Paid**. Building the real inventory takes ~75 subrequests (one per host and group var file,
times two paths), over the free plan's cap of 50.

## Deploy

Every Cloudflare command is an `npm run` script in [`package.json`](package.json), so there is nothing to install
globally and nothing to remember about flags. Run them from the repo root — there is one `pyproject.toml`, and
pywrangler insists on finding `wrangler.jsonc` beside it.

```bash
uv sync
npm install
npm run login
npm run bucket                  # then enable public access on it in the dashboard
$EDITOR instance/config.yml     # src/config.yml is a symlink to it
npm run deploy
scripts/build-token.sh set      # the on-demand build endpoint, see below
scripts/build-token.sh run      # seed the bucket now, rather than waiting for 14:00 UTC
```

`npm run deploy` preflights that `src/config.yml` is a symlink that resolves — a missing or dangling link is
bundled as nothing at all, and the Worker then dies on import with
`FileNotFoundError: /session/metadata/config.yml`. Calling `pywrangler` directly skips that check.

## Running a build

The cron trigger fires daily at 14:00 UTC. **Nothing else fires it**: deploying doesn't, and a deployed cron
trigger cannot be dispatched by hand — `wrangler dev --remote` returns error 1042 rather than sending one. That
is why the Worker also has a token-guarded `fetch` handler, and why a fresh deploy leaves the bucket 404ing until
you use it.

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

**The Cloudflare dashboard cannot fire a cron trigger.** There is no "run now" button; *Settings → Trigger
Events* only lists past runs. The one thing you can click is a URL, so the token is accepted as `?token=` as well
as a bearer header — `scripts/build-token.sh url` prints the whole thing to bookmark.

The trade is that the token then sits in your browser history and Cloudflare's request logs. To avoid that, use
the header form, or put the Worker on a custom domain behind
[Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/) and drop the token.

The guard itself is not optional. The `workers.dev` URL is public and each build costs ~75 requests against
whatever hosts your inventory, so an open endpoint is a free way for anyone to hammer that server. It **fails
closed** — no `BUILD_TOKEN`, no way in — and a wrong token gets a 404 rather than a 403, so it doesn't advertise
itself.

## Checking the last run

`npm run tail` only streams what happens while you're attached; wrangler has no historical log query. To find out
when the site was last rebuilt, ask the site — every run rewrites every page:

```bash
curl -sI https://<your-domain>/index.html | grep -i last-modified
```

Don't use `wrangler r2 bucket info` for this. Its `object_count` is a lagging metric and still read `0` several
minutes after a run had demonstrably written every object.

## URLs

R2 public buckets have no index document, so the site's entry point is **`/index.html`**, not `/`. Every page is
written as `<path>/index.html` and linked that way; bare `/` and `/inventory/x/` have no object key behind them
and 404.

A **URL Rewrite** on the zone in front of the bucket fixes it — a rewrite rather than a redirect, so the address
bar keeps the clean path. It cannot live in `wrangler.jsonc`: the Worker only *writes* objects on its cron
trigger, and requests to the bucket's domain go straight to R2 without reaching it. Being zone config, it does
**not** travel with `npm run deploy`; a new bucket or domain needs it again.

In the dashboard, **Rules → Overview → Create rule → URL Rewrite Rule**, leaving *Query* alone:

| Field                    | Value                                                                     |
| ------------------------ | ------------------------------------------------------------------------- |
| Custom filter expression | `(http.host eq "<your-domain>" and ends_with(http.request.uri.path, "/"))` |
| Path → Rewrite to        | **Dynamic**, `concat(http.request.uri.path, "index.html")`                |

Or through the API — noting that this `PUT` **replaces every rule in the zone's `http_request_transform`
phase**, so if the zone has other URL rewrites, use the dashboard, or `GET` the entrypoint first and re-`PUT`
them alongside this one:

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

Matching on a trailing slash is deliberate: a path with neither a slash nor an extension —
`/inventory/kism_main` — still 404s, and catching those would mean rewriting every extensionless path, which
starts guessing at things like `/static/`. Nothing links that way. Check the result with `curl -sI`; a rewrite
returns `200` with **no** `location:` header, where a redirect would return `301`.
