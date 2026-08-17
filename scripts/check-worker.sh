#!/usr/bin/env bash
# Boots the Worker for real and checks it answers, which is the only way to find out whether the thing
# runs under Pyodide/wasm — nothing in pytest touches that path.
#
# `npm run dev` does two checks in one: pywrangler sync resolves [project.dependencies] against the Pyodide
# index (a dependency with no wasm wheel fails here), then workerd boots the bundle, which runs entry.py's
# module-level config parse and every import. 404 is the right answer to an untokened /refresh, so it means the
# whole chain came up. Anything else, or nothing at all, is a failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

LOG=$(mktemp)
# setsid so the pgid is DEV_PID: `npm run dev` is npm -> uv -> npx -> workerd, and killing only the top
# of that chain leaves workerd holding the port.
setsid npm run dev >"$LOG" 2>&1 &
DEV_PID=$!
trap 'kill -- -$DEV_PID 2>/dev/null || true' EXIT

for _ in $(seq 60); do
  if ! kill -0 "$DEV_PID" 2>/dev/null; then
    echo "wrangler dev exited before serving anything:"
    cat "$LOG"
    exit 1
  fi

  # /refresh rather than any old path: an untokened request 404s either way, but this one runs the token
  # comparison on the way there instead of stopping at the path check.
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/refresh || true)
  case "$code" in
  404)
    # /status is the only handler that touches the R2 binding, and nothing else here would run a line of it.
    # Any status code will do — the bucket is empty in CI, which is a legitimate 503 — the body is the check.
    if ! curl -s http://127.0.0.1:8787/status | grep -q stale_after_seconds; then
      echo "/status did not return its JSON:"
      curl -s -i http://127.0.0.1:8787/status
      cat "$LOG"
      exit 1
    fi
    echo "Worker booted under Pyodide, answered 404 to an untokened request, and served /status."
    exit 0
    ;;
  000) sleep 1 ;; # Not listening yet
  *)
    echo "Expected 404 from the unauthenticated fetch handler, got $code:"
    cat "$LOG"
    exit 1
    ;;
  esac
done

echo "wrangler dev never served a request:"
cat "$LOG"
exit 1
