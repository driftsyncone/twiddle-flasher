#!/usr/bin/env python3
"""Check an assembled site directory (dist/) before it is deployed. Exit 1 on any problem.

 * index.json: every referenced file exists, size and sha256 match, manifests/SHA256SUMS present
 * every manifest follows the esp-web-tools manifest format (src/const.ts at the vendored commit):
   name, version, builds[] with a known chipFamily, optional serialType cdc|uart, parts[] with
   a relative path and a DECIMAL integer offset; the parts exist
 * the update manifest never writes the NVS region, the bootloader or the partition table
 * no runtime request to a third-party host: no external script/stylesheet/import/fetch/@import/url()
   in HTML, CSS or JS (plain <a href> links are fine)
 * every released version has a licence page
 * leak scan of EVERY text file in the site (html, json, js, css, md, txt, svg, webmanifest; the vendored esp-web-tools
   bundle is skipped): local paths (/home/, /Users/, /root/, /tmp/claude), login names and home-network strings, private IPs
   (except the setup portal 192.168.4.1) and e-mail addresses (except the allow-list). The failure names file and pattern only,
   never the matched text.
Standard library only. Usage: check_site.py DIST_DIR
"""
import hashlib
import json
import os
import re
import sys

CHIPS = {"ESP32", "ESP32-C2", "ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-C61", "ESP32-H2", "ESP32-P4", "ESP32-S2", "ESP32-S3", "ESP8266"}
NVS_RANGE = (0x9000, 0x9000 + 0x6000)  # default when a board entry carries no nvs_region (P4 partitions.csv)
# The S3's default_16MB.csv has NVS at 0x9000 with size 0x5000 and otadata (boot_app0) at 0xe000, which an update DOES write,
# so each board states its own region (boards.json nvs_region, copied into index.json).
UPDATE_FORBIDDEN_NAMES = {"bootloader", "partition-table"}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


LEAK_PATTERNS = [
    ("local path /home/", r"/home/"), ("local path /Users/", r"/Users/"), ("local path /root/", r"/root/"),
    ("scratch path /tmp/claude", r"/tmp/claude"), ("home-network .lan host", r"[\w-]+\.lan\b"),
    ("private IP 192.168.x.x", r"\b192\.168\.\d{1,3}\.\d{1,3}\b"), ("private IP 10.x.x.x", r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    ("private IP 172.16-31.x.x", r"\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"),
    ("e-mail address", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
]


def private_patterns():
    """Extra patterns the maintainer keeps OUTSIDE the repository (login names, home domain, ...): one regular expression per
    line in the file named by $TWIDDLE_PRIVATE_DENYLIST. They are never published, so the public code names none of them."""
    p = os.environ.get("TWIDDLE_PRIVATE_DENYLIST", "")
    if not p or not os.path.isfile(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(("private denylist entry", line))
    return out


LEAK_ALLOW = {"192.168.4.1"}  # the setup-portal address the firmware documents
# E-mail addresses: upstream copyright lines in the verbatim licence texts (licenses/<board>/<version>/index.html and licenses.txt)
# are public by nature and must stay unmodified, so they are exempt there; everywhere else only these are allowed (lower-case).
EMAIL_ALLOW = {"noreply@github.com"}
EMAIL_ALLOW_DOMAINS = {"example.com", "example.org", "users.noreply.github.com"}
LEAK_TEXT_EXT = (".html", ".htm", ".json", ".js", ".mjs", ".css", ".md", ".txt", ".svg", ".webmanifest", ".xml", ".map", ".csv", ".yml", ".yaml")
LEAK_SKIP_DIRS = {"vendor"}  # vendored esp-web-tools bundle (scanned by gen_site / vendor-esp-web-tools.sh)


def leak_scan_site(root, patterns=None, extra_allow=()):
    """-> list of 'file: pattern-label' strings (never the matched text)."""
    pats = [(lbl, re.compile(rx, re.I)) for lbl, rx in ((patterns or LEAK_PATTERNS) + private_patterns())]
    allow = LEAK_ALLOW | {a.lower() for a in extra_allow}
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not (d in LEAK_SKIP_DIRS and os.path.relpath(dp, root) == ".")]
        for fn in fns:
            if not fn.lower().endswith(LEAK_TEXT_EXT):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            t = open(p, encoding="utf-8", errors="replace").read()
            for lbl, rx in pats:
                for m in rx.finditer(t):
                    hit = m.group(0).lower()
                    if hit in allow:
                        continue
                    if lbl == "e-mail address" and (hit in EMAIL_ALLOW or hit.rsplit("@", 1)[1] in EMAIL_ALLOW_DOMAINS
                                                    or (rel.startswith("licenses/") and fn in ("index.html", "licenses.txt"))):
                        continue
                    out.append(f"{rel}: leak scan: {lbl}")
                    break
    return out


def check_manifest(path, update, errors, nvs=NVS_RANGE):
    try:
        m = json.load(open(path))
    except ValueError as e:
        errors.append(f"{path}: invalid JSON: {e}")
        return
    base = os.path.dirname(path)
    for k in ("name", "version"):
        if not isinstance(m.get(k), str) or not m[k]:
            errors.append(f"{path}: '{k}' must be a non-empty string")
    for k in ("new_install_prompt_erase",):
        if k in m and not isinstance(m[k], bool):
            errors.append(f"{path}: '{k}' must be boolean")
    if "new_install_improv_wait_time" in m and not isinstance(m["new_install_improv_wait_time"], int):
        errors.append(f"{path}: new_install_improv_wait_time must be an integer")
    if m.get("new_install_prompt_erase") is not True:
        errors.append(f"{path}: new_install_prompt_erase must be true: esp-web-tools erases the whole device silently otherwise")
    builds = m.get("builds")
    if not isinstance(builds, list) or not builds:
        errors.append(f"{path}: builds[] missing")
        return
    for b in builds:
        if b.get("chipFamily") not in CHIPS:
            errors.append(f"{path}: unknown chipFamily {b.get('chipFamily')!r}")
        if "serialType" in b and b["serialType"] not in ("cdc", "uart"):
            errors.append(f"{path}: serialType must be cdc or uart")
        extra = set(b) - {"chipFamily", "parts", "serialType"}
        if extra:
            errors.append(f"{path}: unexpected build keys {sorted(extra)}")
        parts = b.get("parts")
        if not isinstance(parts, list) or not parts:
            errors.append(f"{path}: parts[] missing")
            continue
        for p in parts:
            off, rel = p.get("offset"), p.get("path")
            if not isinstance(off, int) or isinstance(off, bool) or off < 0:
                errors.append(f"{path}: offset {off!r} must be a decimal integer")
                continue
            if not isinstance(rel, str) or rel.startswith(("/", "http")) or ".." in rel.split("/"):
                errors.append(f"{path}: part path {rel!r} must be relative to the manifest")
                continue
            if not os.path.isfile(os.path.join(base, rel)):
                errors.append(f"{path}: part file missing: {rel}")
            if update and (nvs[0] <= off < nvs[1] or off in (0, 0x2000, 0x8000)):
                errors.append(f"{path}: update manifest writes protected offset {off}")
        if len({p.get("offset") for p in parts}) != len(parts):
            errors.append(f"{path}: duplicate offsets")


def check_external(root, errors):
    html_ext = re.compile(r"""<(script|link|img|iframe|source)\b[^>]*\b(src|href)\s*=\s*["'](https?:)?//""", re.I)
    css_ext = re.compile(r"""(@import\s+(url\()?["']?(https?:)?//|url\(\s*["']?(https?:)?//)""", re.I)
    js_ext = re.compile(r"""(\bimport\s*\(\s*["']https?://|\bfrom\s*["']https?://|\bfetch\s*\(\s*["']https?://|new\s+URL\s*\(\s*["']https?://[^"']*["']\s*\)\s*\)?\s*\.\s*href|importScripts\s*\(\s*["']https?://|\.src\s*=\s*["']https?://)""")
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            if fn.endswith((".html", ".htm")):
                t = open(p, encoding="utf-8", errors="replace").read()
                for m in html_ext.finditer(t):
                    if "rel=\"canonical\"" in m.group(0) or "rel='canonical'" in m.group(0):
                        continue
                    errors.append(f"{p}: external resource: {m.group(0)[:100]}")
            elif fn.endswith(".css"):
                if css_ext.search(open(p, encoding="utf-8", errors="replace").read()):
                    errors.append(f"{p}: external @import/url()")
            elif fn.endswith(".js"):
                m = js_ext.search(open(p, encoding="utf-8", errors="replace").read())
                if m:
                    errors.append(f"{p}: runtime request to a third-party host: {m.group(0)[:80]}")


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = argv[1]
    errors = []
    ip = os.path.join(root, "index.json")
    if not os.path.isfile(ip):
        print(f"check_site: {ip} missing", file=sys.stderr)
        return 1
    idx = json.load(open(ip))
    n_versions = 0
    for b in idx["boards"]:
        for v in b["versions"]:
            n_versions += 1
            for key in ("manifest_new", "manifest_update", "sha256sums"):
                if not os.path.isfile(os.path.join(root, v[key])):
                    errors.append(f"{b['id']} {v['version']}: {key} file missing: {v[key]}")
            nvs = tuple(b["nvs_region"]) if b.get("nvs_region") else NVS_RANGE
            check_manifest(os.path.join(root, v["manifest_new"]), False, errors, nvs)
            check_manifest(os.path.join(root, v["manifest_update"]), True, errors, nvs)
            vdir = os.path.dirname(os.path.join(root, v["manifest_new"]))
            for f in v["files"]:
                fp = os.path.join(vdir, f["name"])
                if not os.path.isfile(fp):
                    errors.append(f"missing {fp}")
                elif os.path.getsize(fp) != f["size"] or sha(fp) != f["sha256"]:
                    errors.append(f"size/sha256 mismatch: {fp}")
            sums = os.path.join(root, v["sha256sums"])
            if os.path.isfile(sums):
                for line in open(sums):
                    digest, _, name = line.rstrip("\n").partition("  ")
                    fp = os.path.join(vdir, name)
                    if not os.path.isfile(fp) or sha(fp) != digest:
                        errors.append(f"SHA256SUMS entry fails: {name} in {vdir}")
            if not os.path.isfile(os.path.join(root, "licenses", b["id"], v["version"], "index.html")):
                errors.append(f"{b['id']} {v['version']}: no licence page at licenses/{b['id']}/{v['version']}/index.html")
    check_external(root, errors)
    errors.extend(leak_scan_site(root))
    for e in errors:
        print("FAIL:", e, file=sys.stderr)
    if errors:
        print(f"check_site: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print(f"check_site: ok ({n_versions} board/version pair(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
