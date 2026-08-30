#!/usr/bin/env bash
set -euo pipefail

unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY

echo "[1/5] Asking for sudo password..."
sudo -v

echo "[2/5] Closing Snap VS Code if it is running..."
pkill -f '/snap/code/.*/usr/share/code/code' 2>/dev/null || true
sleep 1

echo "[3/5] Adding Microsoft's official VS Code apt repository..."
sudo apt-get update
sudo apt-get install -y wget curl gpg ca-certificates apt-transport-https

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
key_asc="$tmp_dir/microsoft.asc"
key_gpg="$tmp_dir/packages.microsoft.gpg"

curl -fL --retry 5 --retry-delay 2 \
  https://packages.microsoft.com/keys/microsoft.asc \
  -o "$key_asc"

if ! grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$key_asc"; then
  echo "Downloaded Microsoft key does not look like a PGP key. First lines were:" >&2
  sed -n '1,10p' "$key_asc" >&2
  exit 1
fi

gpg --batch --yes --dearmor -o "$key_gpg" "$key_asc"
sudo install -D -o root -g root -m 644 "$key_gpg" /etc/apt/keyrings/packages.microsoft.gpg

echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" | \
  sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null

echo "[4/5] Installing VS Code .deb package..."
sudo apt-get update
sudo apt-get install -y code

echo "[5/5] Removing Snap VS Code..."
if snap list code >/dev/null 2>&1; then
  sudo snap remove code
fi

echo
echo "Done. Installed VS Code:"
/usr/bin/code --version | sed -n '1,3p'
echo
echo "Launch it with: /usr/bin/code"
