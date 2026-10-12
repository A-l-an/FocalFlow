#!/bin/sh
set -eu
FF_REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FF_PYTHON="${FOCALFLOW_PYTHON:-python3}"
cd "$FF_REPO_ROOT/backend"
"$FF_PYTHON" -B -m unittest discover -v
"$FF_PYTHON" -B tools/manual_testing/manual_test.py --check
cd "$FF_REPO_ROOT/android"
"$FF_PYTHON" -B tests/check_logging_wiring.py
if [ -n "${FF_JSON_JAR:-}" ]; then
    : "${FF_JAVA_HOME:?Set FF_JAVA_HOME for the complete Java checks}"
    : "${FF_ANDROID_JAR:?Set FF_ANDROID_JAR for Android API-signature checks}"
    "$FF_PYTHON" -B tests/run_sensitive_logging_tests.py --json-jar "$FF_JSON_JAR" --java-home "$FF_JAVA_HOME" --android-jar "$FF_ANDROID_JAR" --backend "$FF_REPO_ROOT/backend" --python38 "$FF_PYTHON"
else
    printf '%s
' 'Java/cross-language checks skipped: set FF_JSON_JAR, FF_JAVA_HOME and FF_ANDROID_JAR to existing tools.'
fi
