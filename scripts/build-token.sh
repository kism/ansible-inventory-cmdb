#!/usr/bin/env bash
# BUILD_TOKEN wrangling, and the on-demand build it guards.
#
#   set    generate a token (or take one as $2), store it, upload it to Cloudflare
#   url    print the bookmarkable trigger URL (token in the query string)
#   run    trigger a build on the deployed Worker
#
# .dev.vars is the only copy of the token: `wrangler secret list` returns names, never values, so a token that
# is only on Cloudflare is a token you cannot get back. Lose this file and the fix is `set` (a new one).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DEV_VARS=.dev.vars
TOKEN_HINT="Run: $0 set"
# The workers.dev subdomain is account-specific and no wrangler command reports it, so it lives in .dev.vars
# next to the token, or in the environment.
URL_HINT="Add WORKER_URL=\"https://<worker>.workers.dev\" to $DEV_VARS, or export it."

# $1 from the environment, else the last $1= line in .dev.vars, unquoted and without a trailing slash. Dies
# with the hint in $2 if neither has it.
need() {
	local value=${!1:-$(sed -n "s/^$1=//p" "$DEV_VARS" 2>/dev/null | tail -n1 | tr -d "\"'")}
	[ -n "$value" ] || {
		echo "No $1. $2" >&2
		exit 1
	}
	printf '%s' "${value%/}"
}

case "${1:-}" in
set)
	token=${2:-$(openssl rand -hex 32)}

	# Rewrite rather than append, so repeated runs don't leave stale BUILD_TOKEN lines behind. umask first: the
	# temp file holds the token too, and would otherwise be world-readable for the moment before the mv.
	umask 077
	touch "$DEV_VARS"
	{
		grep -v '^BUILD_TOKEN=' "$DEV_VARS" || true
		echo "BUILD_TOKEN=\"$token\""
	} >"$DEV_VARS.tmp"
	mv "$DEV_VARS.tmp" "$DEV_VARS"
	echo "Wrote BUILD_TOKEN to $DEV_VARS"

	# Piped, so the token never becomes a command-line argument in anyone's shell history or process list.
	worker=$(grep -m1 '"name":' wrangler.jsonc | sed 's/.*: *"\(.*\)".*/\1/')
	printf '%s' "$token" | npx wrangler secret put BUILD_TOKEN --name "$worker"
	;;

url)
	# Assigned first, not inlined into echo: `exit` inside $( ) only leaves the subshell, so echo would happily
	# print a broken URL after the error. A failing assignment trips set -e.
	url=$(need WORKER_URL "$URL_HINT")
	token=$(need BUILD_TOKEN "$TOKEN_HINT")
	echo "$url/?token=$token"
	;;

run)
	url=$(need WORKER_URL "$URL_HINT")
	token=$(need BUILD_TOKEN "$TOKEN_HINT")
	# The header form, not ?token=, so the token stays out of Cloudflare's request logs. Builds take a while:
	# every host and group in the inventory is two fetches.
	curl -sS -X POST --max-time 300 \
		-H "Authorization: Bearer $token" \
		-w '\n[HTTP %{http_code}]\n' \
		"$url"
	;;

*)
	sed -n '2,6p' "$0" | cut -c3-
	exit 1
	;;
esac
