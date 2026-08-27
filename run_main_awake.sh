#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$SCRIPT_DIR"

while true; do
    if caffeinate -dimsu "$PYTHON_BIN" main.py --skipHuman "$@"; then
        exit 0
    else
        exit_code=$?
    fi

    printf '⚠️ main.py 异常退出（exit %s），5 秒后重新拉起...\n' "$exit_code" >&2
    sleep 5
done
