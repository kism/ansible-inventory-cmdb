#!/usr/bin/env bash
# BUILD_TOKEN wrangling, and the on-demand build it guards.
#
#   get    print the token
#   url    print the bookmarkable trigger URL (token in the query string)
#   set    generate a token (or take one as $2), store it, upload it to Cloudflare
#   run    trigger a build on the deployed Worker
#
# .dev.vars is the only copy of the token: `wrangler secret list` returns names, never values, so a token that
# is only on Cloudflare is a token you cannot get back. Lose this file and the fix is `set` (a new one).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

DEV_VARS=.dev.vars

die() {
	echo "$*" >&2
	exit 1
}

# Last KEY= line in .dev.vars, unquoted. Empty (not an error) if the file or key is missing.
read_var() {
	[ -f "$DEV_VARS" ] || return 0
	sed -n "s/^$1=//p" "$DEV_VARS" | tail -n1 | tr -d "\"'"
}

get_token() {
	local token
	token=$(read_var BUILD_TOKEN)
	[ -n "$token" ] || die "No BUILD_TOKEN in $DEV_VARS. Run: $0 set"
	printf '%s' "$token"
}

# The workers.dev subdomain is account-specific and no wrangler command reports it, so it lives in .dev.vars
# next to the token, or in the environment.
get_url() {
	local url=${WORKER_URL:-$(read_var WORKER_URL)}
	[ -n "$url" ] || die "No worker URL. Add WORKER_URL=\"https://<worker>.workers.dev\" to $DEV_VARS, or export it."
	printf '%s' "${url%/}"
}

case "${1:-}" in
get)
	get_token
	echo
	;;

url)
	# Assigned first, not inlined into echo: `die` inside $( ) only exits the subshell, so echo would happily
	# print a broken URL after the error. A failing assignment trips set -e.
	url=$(get_url)
	token=$(get_token)
	echo "$url/?token=$token"
	;;

set)
	token=${2:-$(openssl rand -hex 32)}

	# Rewrite rather than append, so repeated runs don't leave stale BUILD_TOKEN lines behind.
	touch "$DEV_VARS"
	chmod 600 "$DEV_VARS"
	{ grep -v '^BUILD_TOKEN=' "$DEV_VARS" || true; } >"$DEV_VARS.tmp"
	echo "BUILD_TOKEN=\"$token\"" >>"$DEV_VARS.tmp"
	mv "$DEV_VARS.tmp" "$DEV_VARS"
	chmod 600 "$DEV_VARS"
	echo "Wrote BUILD_TOKEN to $DEV_VARS"

	# Piped, so the token never becomes a command-line argument in anyone's shell history or process list.
	worker=$(grep -m1 '"name":' wrangler.jsonc | sed 's/.*: *"\(.*\)".*/\1/')
	printf '%s' "$token" | npx wrangler secret put BUILD_TOKEN --name "$worker"
	;;

run)
	url=$(get_url)
	token=$(get_token)
	# The header form, not ?token=, so the token stays out of Cloudflare's request logs. Builds take a while:
	# every host and group in the inventory is two fetches.
	curl -sS -X POST --max-time 300 \
		-H "Authorization: Bearer $token" \
		-w '\n[HTTP %{http_code}]\n' \
		"$url"
	;;

*)
	sed -n '2,7p' "$0" | cut -c3-
	exit 1
	;;
esac
