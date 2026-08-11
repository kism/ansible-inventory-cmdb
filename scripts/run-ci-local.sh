#!/usr/bin/env bash

set -euo pipefail

function print_heading() {
    echo
    echo "=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-="
    echo "$1 >>>"
}

source .venv/bin/activate

print_heading "ty"
ty check

print_heading "ruff"
ruff format
ruff check --fix

print_heading "PyTest"
pytest -q --tb=short
