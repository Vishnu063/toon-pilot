#!/usr/bin/env bash
# Install only; never load models or start the API server.
set -euo pipefail
revision=ca1e85fe9430179831e6bc6be790c332190a3866
source_url=https://github.com/ace-step/ACE-Step-1.5.git
install_dir="${TOON_MUSIC_DIR:-$HOME/.local/share/toon-pilot/ACE-Step-1.5}"
download_models=false
check_only=false
for arg in "$@"; do
    case "$arg" in
        --download-models) download_models=true ;;
        --check) check_only=true ;;
        *) echo "Usage: bash scripts/install-music.sh [--check] [--download-models]" >&2; exit 2 ;;
    esac
done
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
    echo 'This installer supports Linux x86_64. See docs/ace-step.md for other platforms.' >&2; exit 1;
}
for tool in git curl python3 ffmpeg ffprobe; do
    command -v "$tool" >/dev/null || { echo "Missing $tool; install it first." >&2; exit 1; }
done
[[ "$install_dir" == /* ]] || { echo 'TOON_MUSIC_DIR must be an absolute path.' >&2; exit 1; }
parent="$install_dir"
while [[ ! -d "$parent" ]]; do parent="$(dirname "$parent")"; done
python3 - "$parent" <<'PY'
import shutil, sys
free = shutil.disk_usage(sys.argv[1]).free / 1024**3
print(f'Available disk: {free:.1f} GiB; install preflight requires 25 GiB free.')
if free < 25:
    sys.exit('Not enough disk space. Use a larger existing disk or free space first.')
PY
echo "ACE-Step revision: $revision"
echo "Install directory: $install_dir"
echo 'Upstream Linux dependencies include CUDA wheels, even with CPU runtime.'
echo '8 GB RAM inference is unverified. No server or song is started by this script.'
if "$check_only"; then exit 0; fi

if command -v uv >/dev/null; then
    uv_bin="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_bin="$HOME/.local/bin/uv"
else
    installer="$(mktemp)"
    trap 'rm -f "$installer"' EXIT
    curl --fail --location --silent --show-error https://astral.sh/uv/install.sh -o "$installer"
    sh "$installer"
    uv_bin="$HOME/.local/bin/uv"
    [[ -x "$uv_bin" ]] || { echo 'uv was not found in ~/.local/bin; add uv to PATH and retry.' >&2; exit 1; }
fi
if [[ ! -e "$install_dir" ]]; then
    mkdir -p "$(dirname "$install_dir")"
    git clone --filter=blob:none "$source_url" "$install_dir"
fi
[[ -d "$install_dir/.git" ]] || { echo 'Install directory is not a Git checkout; choose another TOON_MUSIC_DIR.' >&2; exit 1; }
[[ "$(git -C "$install_dir" remote get-url origin)" == "$source_url" ]] || {
    echo 'Existing checkout has a different origin; choose another TOON_MUSIC_DIR.' >&2; exit 1;
}
if [[ -n "$(git -C "$install_dir" status --porcelain --untracked-files=no)" ]]; then
    echo 'Tracked source changes found; refusing to overwrite them.' >&2; exit 1
fi
current="$(git -C "$install_dir" rev-parse --verify HEAD 2>/dev/null || true)"
if [[ "$current" != "$revision" ]]; then
    git -C "$install_dir" fetch --depth=1 origin "$revision"
    git -C "$install_dir" checkout --detach "$revision"
fi
cd "$install_dir"
"$uv_bin" sync --locked --python 3.12 --no-dev
[[ -x .venv/bin/acestep-api ]] || { echo 'ACE-Step API entry point was not installed.' >&2; exit 1; }
if "$download_models"; then
    "$uv_bin" run --no-sync acestep-download
fi
printf '%s\n' "$revision" > .toon-pilot-installed
echo 'Software setup completed. Singing inference has NOT been tested.'
if ! "$download_models"; then echo 'Models were not downloaded; rerun with --download-models to prepare them.'; fi
echo 'Start later from toon-pilot: bash scripts/start-music.sh'
