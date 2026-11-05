#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPO=https://github.com/OliverRhyme/wifit3-termux
API=https://api.github.com/repos/OliverRhyme/wifit3-termux/releases/latest
FALLBACK="$REPO/archive/refs/heads/termux-port.tar.gz"

command -v pkg >/dev/null || { echo "Run this inside Termux." >&2; exit 1; }

pkg install -y python libusb termux-api curl

wheel=$(curl -fsSL "$API" 2>/dev/null | grep -o 'https://[^"]*\.whl' | head -1) || wheel=""

source=$wheel
[ -n "$source" ] || source=$FALLBACK

python -m pip install --force-reinstall --no-cache-dir "$source"

echo
echo "wifit3 installed. Run: wifit3"
echo "Install the Termux:API app from F-Droid or Google Play as well;"
echo "the termux-api package alone is not enough."
