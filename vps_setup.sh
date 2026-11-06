#!/usr/bin/env bash
set +x
set -Eeuo pipefail
APP=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec "$APP/install.sh" "$@"
