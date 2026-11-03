#!/usr/bin/env python3
"""Generate the flasher's per-board/per-version manifests, SHA256SUMS and index.json.

Input: a releases directory with one sub-directory per firmware version:

    releases/<version>/
        tested.json                 written by the maintainer after a hardware pass (REQUIRED)
        notes.md                    release notes (optional, shown as the changelog)
        <anything>.parts.json       emitted by the firmware repo's tools/dist.sh, one per board
        <part>.bin ...              the files the parts.json lists

plus boards.json (the board catalogue). Output (--out):

    fw/<board>/<version>/{<part>.bin, manifest-new.json, manifest-update.json, SHA256SUMS}
    fw/<board>/latest.json
    index.json

The tested-images gate: a version is published only if tested.json lists the board, with a
full checklist and the sha256 of the very app image that was tested. Everything is validated
before anything is written; any failure exits non-zero and leaves --out untouched.
Python 3 standard library only.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

SCHEMA = 1
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REQUIRED_CHECKS = ("boots", "setup_portal", "wifi_join", "ota_from_previous")
CHIP_FAMILIES = {"ESP32", "ESP32-C2", "ESP32-C3", "ESP32-C5", "ESP32-C6", "ESP32-C61",
                 "ESP32-H2", "ESP32-P4", "ESP32-S2", "ESP32-S3", "ESP8266"}


class PublishError(Exception):
    """Raised for anything that must stop publication."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise PublishError(f"{what} missing: {path}")
    except ValueError as e:
        raise PublishError(f"{what} is not valid JSON ({path}): {e}")


def version_key(v):
    """Semver ordering key (prerelease sorts below the release, identifiers compared per semver)."""
    core, _, pre = v.partition("-")
    nums = tuple(int(x) for x in core.split("."))
    if not pre:
        return (nums, 1, ())
    ids = []
    for ident in pre.split("."):
        ids.append((0, int(ident), "") if ident.isdigit() else (1, 0, ident))
    return (nums, 0, tuple(ids))


def check_boards(cfg):
    if cfg.get("schema") != SCHEMA:
        raise PublishError("boards.json: unsupported schema")
    seen = set()
    for b in cfg["boards"]:
        for k in ("id", "name", "chipFamily", "status"):
            if k not in b:
                raise PublishError(f"boards.json: board without '{k}': {b}")
        if b["id"] in seen or not SAFE_NAME_RE.match(b["id"]):
            raise PublishError(f"boards.json: bad or duplicate id {b['id']!r}")
        seen.add(b["id"])
        if b["chipFamily"] not in CHIP_FAMILIES:
            raise PublishError(f"boards.json: {b['id']}: unknown chipFamily {b['chipFamily']!r}")
        if b["status"] == "available":
            lay = b.get("parts_layout")
            if not lay or "app" not in lay or not all(isinstance(o, int) for o in lay.values()):
                raise PublishError(f"boards.json: {b['id']}: parts_layout must map part name to a decimal int offset incl. 'app'")
            up = b.get("update_parts", [])
            if "app" not in up or any(p not in lay for p in up):
                raise PublishError(f"boards.json: {b['id']}: update_parts must be part names from parts_layout and include 'app'")
            nv = b.get("nvs_region")
            if (not isinstance(nv, list) or len(nv) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in nv)
                    or nv[0] >= nv[1]):
                raise PublishError(f"boards.json: {b['id']}: nvs_region must be [start, end] in decimal bytes (the NVS partition of this board's table)")
            # An update must never write the bootloader, the partition table or the NVS partition (settings, Wi-Fi, token).
            bad = [p for p in up if p in ("bootloader", "partition-table") or nv[0] <= lay[p] < nv[1]]
            if bad:
                raise PublishError(f"boards.json: {b['id']}: update_parts {bad} would touch the bootloader, the partition table or NVS")
        elif b["status"] != "unavailable":
            raise PublishError(f"boards.json: {b['id']}: status must be available|unavailable")
    return {b["id"]: b for b in cfg["boards"]}


def validate_tested(tested, version, board, app_sha, path):
    if tested.get("schema") != SCHEMA:
        raise PublishError(f"{path}: unsupported schema")
    if tested.get("version") != version:
        raise PublishError(f"{path}: version {tested.get('version')!r} does not match directory {version!r}")
    entries = [e for e in tested.get("tested", []) if e.get("board") == board["id"]]
    if not entries:
        raise PublishError(f"REFUSED: {version} is not marked as tested for board {board['id']} in {path}")
    if len(entries) > 1:
        raise PublishError(f"{path}: board {board['id']} listed more than once")
    e = entries[0]
    for k, val in list(e.items()) + [("checklist." + ck, cv) for ck, cv in (e.get("checklist") or {}).items()]:
        if isinstance(val, str) and "placeholder" in val.lower():
            raise PublishError(f"REFUSED: {path}: {board['id']}: '{k}' still contains PLACEHOLDER; fill in the real test result")
    for k in ("chip_rev", "date", "tester"):
        if not e.get(k):
            raise PublishError(f"{path}: {board['id']}: '{k}' is required")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", e["date"]):
        raise PublishError(f"{path}: {board['id']}: date must be YYYY-MM-DD")
    checks = e.get("checklist", {})
    for c in REQUIRED_CHECKS:
        if checks.get(c) is not True and not (c == "ota_from_previous" and checks.get(c) == "n/a"):
            raise PublishError(f"REFUSED: {path}: {board['id']}: checklist item '{c}' is not ticked (true)")
    if e.get("app_sha256") != app_sha:
        raise PublishError(f"REFUSED: {path}: {board['id']}: app_sha256 {e.get('app_sha256')!r} is not the sha256 of the "
                           f"app image being published ({app_sha}); the tested image and the published one differ")
    return e


def validate_parts(vdir, version, pj_path, board):
    pj = load_json(pj_path, "parts manifest")
    where = os.path.basename(pj_path)
    if pj.get("schema") != SCHEMA:
        raise PublishError(f"{where}: unsupported schema")
    if pj.get("version") != version:
        raise PublishError(f"{where}: version {pj.get('version')!r} != directory {version!r}")
    if pj.get("chipFamily") != board["chipFamily"]:
        raise PublishError(f"{where}: chipFamily {pj.get('chipFamily')!r} != board's {board['chipFamily']!r}")
    lay = board["parts_layout"]
    parts = pj.get("parts")
    if not parts:
        raise PublishError(f"{where}: no parts")
    names = [p.get("name") for p in parts]
    if sorted(names) != sorted(lay):
        raise PublishError(f"{where}: parts {sorted(names)} do not match the board's layout {sorted(lay)}")
    out = []
    for p in parts:
        name, off, fn = p["name"], p.get("offset"), p.get("file", "")
        if not isinstance(off, int) or isinstance(off, bool):
            raise PublishError(f"{where}: {name}: offset must be a decimal integer, got {off!r}")
        if off != lay[name]:
            raise PublishError(f"{where}: {name}: offset {off} != expected {lay[name]} for {board['id']}")
        if not SAFE_NAME_RE.match(fn):
            raise PublishError(f"{where}: {name}: unsafe file name {fn!r}")
        fp = os.path.join(vdir, fn)
        if not os.path.isfile(fp):
            raise PublishError(f"{where}: {name}: file missing: {fn}")
        size, digest = os.path.getsize(fp), sha256_file(fp)
        if size == 0:
            raise PublishError(f"{where}: {name}: {fn} is empty")
        if p.get("size") is not None and p["size"] != size:
            raise PublishError(f"{where}: {name}: size mismatch for {fn} ({size} != {p['size']})")
        if p.get("sha256") != digest:
            raise PublishError(f"{where}: {name}: checksum mismatch for {fn} (file {digest}, parts.json {p.get('sha256')})")
        out.append({"name": name, "offset": off, "file": fn, "size": size, "sha256": digest, "path": fp})
    out.sort(key=lambda x: x["offset"])
    for a, b in zip(out, out[1:]):
        if a["offset"] + a["size"] > b["offset"]:
            raise PublishError(f"{where}: {a['name']} ({a['size']} bytes at {a['offset']}) overlaps {b['name']} at {b['offset']}")
    nv = board.get("nvs_region")
    if nv:
        for x in out:
            if x["name"] in board["update_parts"] and x["offset"] < nv[1] and x["offset"] + x["size"] > nv[0]:
                raise PublishError(f"{where}: {x['name']} ({x['size']} bytes at {x['offset']}) would overwrite the NVS region {nv}, "
                                   f"which an update must keep")
    app = next(x for x in out if x["name"] == "app")
    if board.get("app_max_size") and app["size"] > board["app_max_size"]:
        raise PublishError(f"{where}: app is {app['size']} bytes, larger than the {board['app_max_size']}-byte slot")
    return pj, out


def leak_scan(parts, patterns, allow):
    """Fail if a binary contains a forbidden byte string (home-network strings etc.).
    A match whose exact text is in `allow` (e.g. the setup portal address 192.168.4.1) is ignored."""
    allowed = {a.lower() for a in allow}
    for p in parts:
        with open(p["path"], "rb") as f:
            data = f.read()
        extra = []
        pdl = os.environ.get("TWIDDLE_PRIVATE_DENYLIST", "")  # maintainer-only patterns kept outside the repo (see check_site.py)
        if pdl and os.path.isfile(pdl):
            extra = [l.strip() for l in open(pdl, encoding="utf-8") if l.strip() and not l.lstrip().startswith("#")]
        for pat in list(patterns) + extra:
            for m in re.finditer(pat.encode(), data, flags=re.I):
                hit = m.group(0).decode("latin-1")
                if hit.lower() in allowed:
                    continue
                ctx = data[max(0, m.start() - 24):m.end() + 24]
                raise PublishError(f"REFUSED: leak scan: {p['file']} contains {hit!r} near {ctx!r}")


def build_manifest(board, version, parts, mode):
    use = parts if mode == "new" else [p for p in parts if p["name"] in board["update_parts"]]
    build = {"chipFamily": board["chipFamily"]}
    if board.get("serialType"):
        build["serialType"] = board["serialType"]
    build["parts"] = [{"path": p["file"], "offset": p["offset"]} for p in use]
    m = {"name": f"Twiddle for {board['name']}" + (" (update, keeps settings)" if mode == "update" else ""),
         "version": version,
         # esp-web-tools ERASES THE WHOLE DEVICE when this is absent or false (it only asks when true), so both
         # manifests set it: the dialog then shows an "Erase device" checkbox, unticked by default. Update mode
         # tells the user to leave it unticked. Found on a real P4 on 2026-11-02, see README.
         "new_install_prompt_erase": True,
         "new_install_improv_wait_time": 0,
         "builds": [build]}
    return m


def plan(releases, cfg, only_version=None, scan=True):
    boards = check_boards(cfg)
    if not os.path.isdir(releases):
        raise PublishError(f"releases directory missing: {releases}")
    versions = sorted(d for d in os.listdir(releases) if os.path.isdir(os.path.join(releases, d)))
    if only_version:
        versions = [v for v in versions if v == only_version]
    published = {}  # board id -> list of version records
    for version in versions:
        if not VERSION_RE.match(version):
            raise PublishError(f"directory name {version!r} is not a version like 2.0.0 or 2.0.0-p4.10")
        vdir = os.path.join(releases, version)
        pjs = sorted(f for f in os.listdir(vdir) if f.endswith(".parts.json"))
        if not pjs:
            raise PublishError(f"{version}: no *.parts.json found")
        tested_path = os.path.join(vdir, "tested.json")
        if not os.path.isfile(tested_path):
            raise PublishError(f"REFUSED: {version} has no tested.json: only tested images are published")
        tested = load_json(tested_path, "tested.json")
        notes = ""
        if os.path.isfile(os.path.join(vdir, "notes.md")):
            with open(os.path.join(vdir, "notes.md"), encoding="utf-8") as f:
                notes = f.read().strip()
        seen_boards = set()
        for pjf in pjs:
            pj_path = os.path.join(vdir, pjf)
            bid = load_json(pj_path, "parts manifest").get("board")
            board = boards.get(bid)
            if board is None:
                raise PublishError(f"{pjf}: unknown board {bid!r}")
            if board["status"] != "available":
                raise PublishError(f"REFUSED: board {bid} is marked unavailable in boards.json: {board.get('unavailable_reason', '')}")
            if bid in seen_boards:
                raise PublishError(f"{version}: two parts manifests for board {bid}")
            seen_boards.add(bid)
            pj, parts = validate_parts(vdir, version, pj_path, board)
            app = next(p for p in parts if p["name"] == "app")
            t = validate_tested(tested, version, board, app["sha256"], tested_path)
            if scan:
                leak_scan(parts, cfg.get("leak_scan", {}).get("patterns", []), cfg.get("leak_scan", {}).get("allow", []))
            rec = {"version": version, "notes": notes, "tested": t, "flash": pj.get("flash", {}),
                   "parts": parts, "board": board}
            published.setdefault(bid, []).append(rec)
        # tested.json entries that match no published board are almost certainly a typo
        for e in tested.get("tested", []):
            if e.get("board") not in seen_boards:
                raise PublishError(f"{tested_path}: lists board {e.get('board')!r} but {version} has no parts manifest for it")
    return boards, published


def write_output(out, cfg, boards, published):
    parent = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(parent, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=".gen-site-", dir=parent)
    try:
        index_boards = []
        for b in cfg["boards"]:
            recs = sorted(published.get(b["id"], []), key=lambda r: version_key(r["version"]), reverse=True)
            entry = {k: v for k, v in b.items() if k not in ("parts_layout", "update_parts", "app_max_size")}
            entry["versions"] = []
            for r in recs:
                vrel = f"fw/{b['id']}/{r['version']}"
                vdir = os.path.join(stage, vrel)
                os.makedirs(vdir)
                sums = []
                for p in r["parts"]:
                    shutil.copyfile(p["path"], os.path.join(vdir, p["file"]))
                for mode in ("new", "update"):
                    m = build_manifest(b, r["version"], r["parts"], mode)
                    with open(os.path.join(vdir, f"manifest-{mode}.json"), "w", encoding="utf-8") as f:
                        json.dump(m, f, indent=2); f.write("\n")
                for fn in sorted(os.listdir(vdir)):
                    sums.append(f"{sha256_file(os.path.join(vdir, fn))}  {fn}")
                with open(os.path.join(vdir, "SHA256SUMS"), "w", encoding="utf-8") as f:
                    f.write("\n".join(sums) + "\n")
                layout = next(p for p in r["parts"] if p["name"] == "partition-table")["sha256"] if any(p["name"] == "partition-table" for p in r["parts"]) else None
                entry["versions"].append({
                    "version": r["version"], "released": r["tested"]["date"], "notes": r["notes"],
                    "tested": {k: r["tested"][k] for k in ("chip_rev", "date", "tester") } | {k: r["tested"][k] for k in ("variants_tested", "app_sha256") if k in r["tested"]},
                    "layout_sha256": layout,
                    "manifest_new": f"{vrel}/manifest-new.json", "manifest_update": f"{vrel}/manifest-update.json",
                    "sha256sums": f"{vrel}/SHA256SUMS",
                    "files": [{"name": p["file"], "part": p["name"], "offset": p["offset"], "size": p["size"], "sha256": p["sha256"]} for p in r["parts"]],
                })
            entry["latest"] = entry["versions"][0]["version"] if entry["versions"] else None
            if entry["latest"]:
                bd = os.path.join(stage, "fw", b["id"])
                os.makedirs(bd, exist_ok=True)
                with open(os.path.join(bd, "latest.json"), "w", encoding="utf-8") as f:
                    json.dump({"board": b["id"], "version": entry["latest"],
                               "manifest_new": entry["versions"][0]["manifest_new"],
                               "manifest_update": entry["versions"][0]["manifest_update"]}, f, indent=2); f.write("\n")
            index_boards.append(entry)
        with open(os.path.join(stage, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": SCHEMA, "project": cfg.get("project", "Twiddle"), "boards": index_boards}, f, indent=2); f.write("\n")
        os.makedirs(out, exist_ok=True)
        for name in ("fw",):
            shutil.rmtree(os.path.join(out, name), ignore_errors=True)
            if os.path.isdir(os.path.join(stage, name)):
                shutil.copytree(os.path.join(stage, name), os.path.join(out, name))
        shutil.copyfile(os.path.join(stage, "index.json"), os.path.join(out, "index.json"))
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--releases", required=True, help="directory of <version>/ release folders")
    ap.add_argument("--boards", default=os.path.join(os.path.dirname(__file__), "..", "boards.json"))
    ap.add_argument("--out", required=True, help="site directory to write fw/ and index.json into")
    ap.add_argument("--version", help="only this version")
    ap.add_argument("--no-leak-scan", action="store_true")
    a = ap.parse_args(argv)
    try:
        cfg = load_json(a.boards, "boards.json")
        boards, published = plan(a.releases, cfg, a.version, scan=not a.no_leak_scan)
        write_output(a.out, cfg, boards, published)
    except PublishError as e:
        print(f"gen_site: {e}", file=sys.stderr)
        return 1
    n = sum(len(v) for v in published.values())
    print(f"gen_site: published {n} board/version pair(s) into {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
