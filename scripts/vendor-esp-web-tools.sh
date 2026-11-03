#!/bin/sh
# Rebuild the vendored esp-web-tools bundle from the pinned commit in a throwaway dir (needs git, node, npm, jq).
# Usage: scripts/vendor-esp-web-tools.sh   (network needed; the SITE needs none at runtime)
set -eu
PIN=b027c3c939dd660e1f7abb7efd6404839453e759
here=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git clone -q https://github.com/esphome/esp-web-tools.git "$tmp/src"
cd "$tmp/src"; git checkout -q "$PIN"
npm ci --no-audit --no-fund >/dev/null
sh script/build
dst="$here/site/vendor/esp-web-tools"
find "$dst" -maxdepth 1 -name '*.js' -delete
cp dist/web/*.js "$dst/"
cp LICENSE "$dst/LICENSE"
cd node_modules
cp esptool-js/LICENSE "$dst/licenses/esptool-js.LICENSE"
cp improv-wifi-serial-sdk/LICENSE "$dst/licenses/improv-wifi-serial-sdk.LICENSE"
cp lit/LICENSE "$dst/licenses/lit.LICENSE"
cp @material/web/LICENSE "$dst/licenses/material-web.LICENSE"
cp tslib/LICENSE.txt "$dst/licenses/tslib.LICENSE"
cp esptool-js/node_modules/pako/LICENSE "$dst/licenses/pako.LICENSE"
cp atob-lite/LICENSE.md "$dst/licenses/atob-lite.LICENSE"
( cd "$dst" && sha256sum *.js )
echo "Update the hashes in VENDOR.md."
