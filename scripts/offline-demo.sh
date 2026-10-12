#!/bin/sh
set -eu
FF_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$FF_REPO_ROOT/backend"
exec "${FOCALFLOW_PYTHON:-python3}" -B -m examples.offline_demo "$@"
