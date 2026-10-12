#!/usr/bin/env bash
set -euo pipefail

if command -v caffeinate >/dev/null 2>&1; then
    exec caffeinate -i python3 "$@"
fi

exec python3 "$@"

