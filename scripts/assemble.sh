#!/bin/sh
# Assemble the deployable site into dist/ from site/ and a directory of release folders.
#   scripts/assemble.sh RELEASES_DIR [OUT_DIR]      (OUT_DIR defaults to dist)
# RELEASES_DIR/<version>/ holds, per board: <name>.parts.json + the part files (from the firmware repo's tools/dist.sh),
# tested.json and notes.md (maintainer-written), and the licence page for each board: either licenses-<board-id>/ (output of
# scripts/gen_notices.py, already generated) or notices.json {"<board-id>": {"project": FW_REPO, "build": FW_BUILD_DIR}}, in which
# case assemble.sh runs gen_notices.py --check itself and stops on any FAIL (warnings are printed). For a PlatformIO / Arduino-ESP32
# board (the ESP32-S3) the spec adds "tool": "pio" and optionally "compdb": compile_commands.json path and "assets": a JSON file
# listing the LGPL release assets: assemble.sh then runs gen_notices_pio.py (LGPL inventory from the link map) instead. The page ends up in
# site/licenses/<board-id>/<version>/.
# Refuses (non-zero exit, nothing deployed) when: a version has no tested.json / board not listed / checksum or offset
# mismatch (gen_site.py), a version has no licence page, or the assembled tree fails check_site.py.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
rel=${1:?usage: assemble.sh RELEASES_DIR [OUT_DIR]}
out=${2:-$here/dist}
[ -d "$rel" ] || { echo "no such releases directory: $rel" >&2; exit 1; }
tmp=$(mktemp -d "$(dirname "$out")/.assemble.XXXXXX"); trap 'rm -rf "$tmp"' EXIT
cp -R "$here/site/." "$tmp/"
rm -f "$tmp/licenses/.gitkeep"
python3 "$here/scripts/gen_site.py" --releases "$rel" --boards "$here/boards.json" --out "$tmp"
# licence pages: one per published board/version
python3 - "$rel" "$tmp" "$here" <<'PY'
import json, os, shutil, subprocess, sys
rel, out, here = sys.argv[1:4]
idx = json.load(open(os.path.join(out, "index.json")))
for b in idx["boards"]:
    for v in b["versions"]:
        src = os.path.join(rel, v["version"], "licenses-" + b["id"])
        nj = os.path.join(rel, v["version"], "notices.json")
        if not os.path.isfile(os.path.join(src, "index.html")) and os.path.isfile(nj):
            spec = json.load(open(nj)).get(b["id"])
            if spec:
                gen = os.path.join(out, ".notices-" + b["id"])
                tool = "gen_notices_pio.py" if spec.get("tool") == "pio" else "gen_notices.py"
                cmd = [sys.executable, os.path.join(here, "scripts", tool), "--project", spec["project"],
                       "--build", spec["build"], "--version", v["version"], "--board", b.get("name", b["id"]),
                       "--out", gen, "--check"]
                if spec.get("tool") == "pio":
                    if spec.get("compdb"): cmd += ["--compdb", spec["compdb"]]
                    if spec.get("assets"): cmd += ["--assets", spec["assets"]]
                r = subprocess.run(cmd)
                if r.returncode != 0:
                    sys.exit("REFUSED: the notices check failed for %s %s (see FAIL lines above)" % (b["id"], v["version"]))
                src = gen
        if not os.path.isfile(os.path.join(src, "index.html")):
            sys.exit("REFUSED: %s %s has no licences-%s/index.html in the release (run gen_notices.py --check on its build)" % (b["id"], v["version"], b["id"]))
        shutil.copytree(src, os.path.join(out, "licenses", b["id"], v["version"]))
        shutil.rmtree(os.path.join(out, ".notices-" + b["id"]), ignore_errors=True)
PY
python3 "$here/scripts/check_site.py" "$tmp"
rm -rf "$out"; mv "$tmp" "$out"; trap - EXIT
echo "assembled $out"
