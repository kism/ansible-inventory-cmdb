#!/usr/bin/env bash
# Everything the workflows in .github/workflows run, in one go
set -euo pipefail
cd "$(dirname "$0")/.."

function print_heading() {
    echo
    echo "=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-="
    echo "$1 >>>"
}

print_heading "Ruff & Biome"
pnpm format

print_heading "ty"
pnpm typecheck

print_heading "pytest"
pnpm test -q --tb=short

print_heading "Frontend"
pnpm test:frontend
pnpm build

print_heading "Fonts"
pnpm check_fonts

print_heading "Worker (Pyodide)"
pnpm check_worker
