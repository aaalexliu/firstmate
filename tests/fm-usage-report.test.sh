#!/usr/bin/env bash
# Public-CLI tests for local usage importers, deduplication, attribution,
# quota fitting/scaling, private rendering, and launchd definition lifecycle.
set -eu
# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
python3 "$ROOT/tests/usage_report_cases.py"
