#!/bin/zsh
set -eu
FF_ENTRY_DIR="${0:A:h}"
exec "${FOCALFLOW_PYTHON:-python3}" -B "$FF_ENTRY_DIR/manual_test.py" "$@"
