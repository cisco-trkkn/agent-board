#!/usr/bin/env bash
# Install the glab CLI: Homebrew if present, otherwise the official release binary into ~/.local/bin.
set -euo pipefail

if command -v glab >/dev/null 2>&1; then
  echo "glab already installed: $(command -v glab) ($(glab version | head -1))"
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  brew install glab
  exit 0
fi

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
case "$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac
dest="${GLAB_INSTALL_DIR:-$HOME/.local/bin}"

meta=$(curl -fsSL "https://gitlab.com/api/v4/projects/gitlab-org%2Fcli/releases?per_page=1")
read -r tag url sums < <(GLAB_META="$meta" python3 -c '
import json, os, sys
os_, arch = sys.argv[1], sys.argv[2]
rel = json.loads(os.environ["GLAB_META"])[0]
links = rel["assets"]["links"]
asset = next(l["url"] for l in links if l["name"].endswith(f"_{os_}_{arch}.tar.gz"))
sums = next((l["url"] for l in links if l["name"] == "checksums.txt"), "")
print(rel["tag_name"], asset, sums)
' "$os" "$arch")

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "downloading glab $tag ($os/$arch)"
curl -fsSL "$url" -o "$tmp/glab.tar.gz"
if [[ -n "$sums" ]]; then
  expected=$(curl -fsSL "$sums" | awk -v n="glab_${tag#v}_${os}_${arch}.tar.gz" '$2==n {print $1}')
  actual=$(shasum -a 256 "$tmp/glab.tar.gz" | awk '{print $1}')
  [[ -n "$expected" && "$expected" == "$actual" ]] || { echo "checksum mismatch"; exit 1; }
  echo "checksum ok"
fi
tar -xzf "$tmp/glab.tar.gz" -C "$tmp"
mkdir -p "$dest"
install -m 0755 "$(find "$tmp" -type f -name glab | head -1)" "$dest/glab"
echo "installed $dest/glab"
case ":$PATH:" in *":$dest:"*) ;; *) echo "NOTE: add $dest to your PATH (e.g. in ~/.zshrc)";; esac
