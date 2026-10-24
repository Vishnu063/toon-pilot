#!/usr/bin/env bash
# Rootless Debian installation, retaining apt signature and package hash checks.
set -euo pipefail
source /etc/os-release
if [[ "$ID" != debian || "$VERSION_ID" != 13 || "$(dpkg --print-architecture)" != amd64 ]]; then
  echo 'This rootless installer targets Debian 13 amd64 only. Install espeak-ng through your OS package manager instead.' >&2
  exit 1
fi
tools_dir="${TOON_TOOLS_DIR:-/workspace/tools}"
mkdir -p "$tools_dir/apt/lists/partial" "$tools_dir/apt/archives/partial" "$tools_dir/espeak" "$tools_dir/bin"
for tool in apt-get dpkg-deb; do
  command -v "$tool" >/dev/null || { echo "Missing $tool; install eSpeak NG using your OS package manager." >&2; exit 1; }
done
cat > "$tools_dir/apt/sources.list" <<'EOF'
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian trixie main
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian-security trixie-security main
EOF
cat > "$tools_dir/apt/apt.conf" <<'EOF'
Dir::Etc::parts "-";
Dir::Etc::main "-";
EOF
apt_options=(-o "Dir::Etc::sourcelist=$tools_dir/apt/sources.list" -o Dir::Etc::sourceparts=-
  -o "Dir::State::lists=$tools_dir/apt/lists" -o "Dir::Cache::archives=$tools_dir/apt/archives" -o Acquire::Retries=0)
APT_CONFIG="$tools_dir/apt/apt.conf" apt-get "${apt_options[@]}" update
(
  cd "$tools_dir/apt/archives"
  APT_CONFIG="$tools_dir/apt/apt.conf" apt-get "${apt_options[@]}" download espeak-ng libespeak-ng1 espeak-ng-data libpcaudio0 libsonic0 time
  for package in ./*.deb; do dpkg-deb -x "$package" "$tools_dir/espeak"; done
)
cat > "$tools_dir/bin/espeak-ng" <<EOF
#!/bin/sh
export LD_LIBRARY_PATH='$tools_dir/espeak/usr/lib/x86_64-linux-gnu'\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export ESPEAK_DATA_PATH='$tools_dir/espeak/usr/lib/x86_64-linux-gnu'
exec '$tools_dir/espeak/usr/bin/espeak-ng' "\$@"
EOF
chmod +x "$tools_dir/bin/espeak-ng"
"$tools_dir/bin/espeak-ng" --version
echo "Add $tools_dir/bin to PATH before starting the dashboard or production worker."
