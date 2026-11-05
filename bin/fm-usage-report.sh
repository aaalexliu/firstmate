#!/usr/bin/env bash
# fm-usage-report.sh - import local accounting and build an offline usage report.
# Usage and accounting contract: fm-usage-report.sh --help
# Requires python3 (standard library only). Never reads credentials itself.
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export FM_HOME="${FM_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
exec python3 "$SCRIPT_DIR/fm_usage_report.py" "$@"
