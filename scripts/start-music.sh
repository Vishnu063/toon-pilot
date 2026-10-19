#!/usr/bin/env bash
set -euo pipefail
install_dir="${TOON_MUSIC_DIR:-$HOME/.local/share/toon-pilot/ACE-Step-1.5}"
[[ -f "$install_dir/.toon-pilot-installed" && -x "$install_dir/.venv/bin/acestep-api" ]] || {
    echo 'Run bash scripts/install-music.sh first.' >&2; exit 1;
}
# Use the installed entry point directly: uv run could resync dependencies later.
cd "$install_dir"
export ACESTEP_DEVICE=cpu ACESTEP_INIT_LLM=false ACESTEP_LM_BACKEND=pt
export ACESTEP_USE_FLASH_ATTENTION=false ACESTEP_CONFIG_PATH=acestep-v15-turbo
export ACESTEP_API_HOST=127.0.0.1 ACESTEP_API_PORT=8001 ACESTEP_QUEUE_WORKERS=1
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
exec .venv/bin/acestep-api
