#!/usr/bin/env bash
# Opt-in one-shot scheduler entry point. No uploads by default.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="${TOON_TOOLS_DIR:-/workspace/tools}/bin:$PATH"
.venv/bin/python production.py daily --timezone Asia/Kolkata "$@"
.venv/bin/python production.py worker
