#!/usr/bin/env bash
set -Eeuo pipefail
APP=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
while IFS= read -r -d '' file; do bash -n "$file"; done < <(find "$APP" -name '*.sh' -print0)
mapfile -d '' scripts < <(find "$APP" -name '*.sh' -print0)
shellcheck -x -P "$APP" "${scripts[@]}"
python3 -m pytest "$APP/tests/unit" -q
if [[ ${RUN_DOCKER_INTEGRATION:-0} == 1 ]]; then
    python3 -m pytest "$APP/tests/integration" -q -s
else
    printf 'NOT RUN: Docker integration (set RUN_DOCKER_INTEGRATION=1)\n'
fi
