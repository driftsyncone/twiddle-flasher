#!/bin/sh
# Rewrite the site's base URL for another host (Cloudflare Pages, Codeberg Pages, nginx ...).
#   scripts/relocate.sh DIST_DIR NEW_BASE_URL [NEW_SOURCE_URL]
# Example: scripts/relocate.sh dist https://flash.example.org/twiddle/
# All links in the site are relative, so the files work from any path. This only changes the places that carry an
# absolute address: config.json "base_url" (and "source_url"/"issues_url" when NEW_SOURCE_URL is given) and a
# <link rel="canonical"> if present. It refuses to run if the old base URL is still found in the tree afterwards.
set -eu
dist=${1:?usage: relocate.sh DIST_DIR NEW_BASE_URL [NEW_SOURCE_URL]}
new=${2:?usage: relocate.sh DIST_DIR NEW_BASE_URL [NEW_SOURCE_URL]}
src=${3:-}
cfg="$dist/config.json"
[ -f "$cfg" ] || { echo "no $cfg: is $dist an assembled site?" >&2; exit 1; }
case "$new" in https://*|http://localhost*|http://127.0.0.1*) ;; *) echo "NEW_BASE_URL must be https:// (Web Serial needs a secure origin; http://localhost is allowed for tests)" >&2; exit 1 ;; esac
python3 - "$dist" "$new" "$src" <<'PY'
import json, os, re, sys
dist, new, src = sys.argv[1:4]
new = new.rstrip("/") + "/"
cfg_path = os.path.join(dist, "config.json")
cfg = json.load(open(cfg_path))
old = cfg.get("base_url", "")
cfg["base_url"] = new
if src:
    cfg["source_url"] = src
    cfg["issues_url"] = src.rstrip("/") + "/issues"
json.dump(cfg, open(cfg_path, "w"), indent=2); open(cfg_path, "a").write("\n")
canon = re.compile(r'(<link\s+rel="canonical"\s+href=")[^"]*(")', re.I)
for dp, _, fns in os.walk(dist):
    for fn in fns:
        if fn.endswith(".html"):
            p = os.path.join(dp, fn)
            t = open(p, encoding="utf-8").read()
            rel = os.path.relpath(p, dist)
            page = "" if fn == "index.html" and dp == dist else rel.replace("index.html", "")
            t2 = canon.sub(lambda m: m.group(1) + new + page + m.group(2), t)
            if t2 != t:
                open(p, "w", encoding="utf-8").write(t2)
if old and old != new:
    left = []
    for dp, _, fns in os.walk(dist):
        for fn in fns:
            if fn.endswith((".html", ".json", ".js", ".css", ".md", ".txt")):
                if old in open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read():
                    left.append(os.path.join(dp, fn))
    if left:
        sys.exit("old base URL %s is still referenced in: %s" % (old, ", ".join(left)))
print("relocated to", new)
PY
