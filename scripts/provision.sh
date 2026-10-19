#!/usr/bin/env bash
# Sets up everything a deploy needs that isn't in the repo: the R2 bucket, its CORS policy and custom domain, and
# the Worker's BUILD_TOKEN secret. Run once before connecting the repo to Workers Builds; safe to re-run, each
# step skips what's already there.
#
# Nothing here names a deployment. It reads the Worker and bucket names from wrangler.jsonc, the API's domain from
# frontend/.env.cloudflare and the frontend's from wrangler.jsonc's routes, so a fork edits those and runs this.
# The zone ID for the API's domain comes from $CF_ZONE_ID, or a prompt; it's on the domain's dashboard overview.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

wrangler() { pnpm exec wrangler "$@"; }
# The first `"key": "value"` in a file. Good enough for wrangler.jsonc, which has one of each of these.
first() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$2" | head -n1; }

WORKER=$(first name wrangler.jsonc)
BUCKET=$(first bucket_name wrangler.jsonc)
FRONTEND_HOST=$(first pattern wrangler.jsonc)
API_HOST=$(sed -n 's|^VITE_API_BASE=https\?://\([^/]*\).*|\1|p' frontend/.env.cloudflare)
DEV_VARS=.dev.vars

echo "Worker $WORKER, bucket $BUCKET, API at ${API_HOST:?no VITE_API_BASE in frontend/.env.cloudflare}"

if wrangler whoami 2>&1 | grep -q 'not authenticated'; then
  wrangler login --browser false
fi

if wrangler r2 bucket info "$BUCKET" >/dev/null 2>&1; then
  echo "Bucket $BUCKET already exists"
else
  wrangler r2 bucket create "$BUCKET"
fi

# GET/HEAD from anywhere: the data is public anyway, and a named origin would also block the frontend's
# workers.dev and preview URLs. Set every run, since it overwrites.
cors=$(mktemp)
trap 'rm -f "$cors"' EXIT
echo '{"rules":[{"allowed":{"origins":["*"],"methods":["GET","HEAD"]},"maxAgeSeconds":86400}]}' >"$cors"
wrangler r2 bucket cors set "$BUCKET" --file "$cors" --force

if [[ $API_HOST == *.r2.dev ]]; then
  echo "API is on the bucket's r2.dev URL, no custom domain to add"
elif wrangler r2 bucket domain list "$BUCKET" 2>/dev/null | grep -q "domain: *$API_HOST$"; then
  echo "Bucket is already on $API_HOST"
else
  zone=${CF_ZONE_ID:-}
  [ -n "$zone" ] || read -rp "Zone ID for $API_HOST (the domain's dashboard overview page): " zone
  wrangler r2 bucket domain add "$BUCKET" --domain "$API_HOST" --zone-id "$zone" --min-tls 1.2
fi

# .dev.vars (gitignored) is the only copy of the token: `wrangler secret list` returns names, never values. Reused
# if there is one, so re-running this doesn't break a bookmarked URL; delete the line from .dev.vars to rotate it.
token=$(sed -n 's/^BUILD_TOKEN=//p' "$DEV_VARS" 2>/dev/null | tail -n1 | tr -d "\"'")
if [ -z "$token" ]; then
  token=$(openssl rand -hex 32)
  # umask first: the file holds the token, and would otherwise be world-readable.
  umask 077
  echo "BUILD_TOKEN=\"$token\"" >>"$DEV_VARS"
  echo "Wrote a new BUILD_TOKEN to $DEV_VARS"
fi
# Piped, so the token never shows up in shell history or the process list. With stdin piped, wrangler creates a
# draft Worker if this one doesn't exist yet, so this works before the first deploy.
printf '%s' "$token" | wrangler secret put BUILD_TOKEN --name "$WORKER"

url="https://${FRONTEND_HOST:-<your worker>.workers.dev}"
cat <<EOF

Done. Next:
  1. Connect the repo: Workers & Pages -> $WORKER -> Settings -> Build, with
       Build command   pipx install uv
       Deploy command  pnpm run deploy
  2. Once it has deployed, seed the bucket rather than waiting for the cron:
       curl -X POST -H "Authorization: Bearer $token" $url/refresh
     or bookmark $url/refresh?token=$token
EOF
