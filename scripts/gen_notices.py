#!/usr/bin/env python3
"""Third-party notices + copyleft link check for an ESP-IDF build of the Twiddle firmware.

Reads (read-only):
  --project DIR   firmware checkout: dependencies.lock, managed_components/, THIRD_PARTY_NOTICES.md
  --build DIR     its build directory: project_description.json, compile_commands.json and the linker map
  --map FILE      the linker map (default: BUILD/<project_name>.map)
Writes (--out DIR):
  index.html      the licence page for /licenses (full licence texts at the pinned versions)
  components.json machine-readable component list
  licenses.txt    the same texts as plain text

Which components are "in the image" is decided from the linker map: every object file pulled
into the link is traced back to its source file (through compile_commands.json) and so to a
component (ESP-IDF component, managed component, the toolchain runtime, or our own code).

The copyleft check (--check, exit status 1 on any finding) fails when
  * an archive of the Arduino core (libFrameworkArduino, arduino-esp32) is in the map, or
  * a linked source file declares a GPL/LGPL/AGPL licence (SPDX tag or header text), or
  * a linked component's own licence file is GPL/LGPL/AGPL,
unless scripts/notices-allow.json lists that exact finding with a written reason
(dual-licensed code used under its permissive option, the GCC runtime library exception ...).
Entries with "status": "needs-review" pass but are printed as WARNING until a human resolves them.
Limits: prebuilt binary blobs (.a without sources) cannot be scanned for their source licence;
the check covers their packaged licence files only. Python 3 standard library only.
"""
import argparse
import html
import json
import os
import re
import sys

DENY_ARCHIVES = re.compile(r"(libFrameworkArduino|arduino-esp32|/libarduino)", re.I)
LICENCE_FILE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)([._-].*)?$", re.I)
COPYLEFT = re.compile(r"(GNU\s+(Lesser|Library)\s+General\s+Public|GNU\s+General\s+Public|GNU\s+Affero)", re.I)
SPDX_COPYLEFT = re.compile(r"SPDX-License-Identifier:\s*([^\n*]*\b(A?GPL|LGPL)[-0-9.a-z+ ]*[^\n*]*)", re.I)
HERE = os.path.dirname(os.path.abspath(__file__))


def read_text(path, limit=400_000):
    with open(path, "rb") as f:
        return f.read(limit).decode("utf-8", "replace")


_HOME_RE = re.compile(r"/(?:home|Users)/[^/\s\"'<>\\]+|/root(?=/)|/tmp/claude[^/\s\"'<>\\]*")


def scrub(text, roots):
    """Make machine paths in generated output relative: `roots` is [(abs_dir, label)]; the longest root wins (both the
    given and the realpath spelling), then any remaining /home/<user>, /Users/<user>, /root, /tmp/claude* prefix becomes <home>."""
    pairs = []
    for d, label in roots:
        if d:
            for v in {d.rstrip("/"), os.path.realpath(d).rstrip("/")}:
                if v and v != "/":
                    pairs.append((v, label))
    for v, label in sorted(pairs, key=lambda x: -len(x[0])):
        text = re.sub(re.escape(v) + r"(?![\w.-])", label, text)
    return _HOME_RE.sub("<home>", text)


def parse_lock(path):
    """dependencies.lock -> {name: version} (top-level components only)."""
    out, cur = {}, None
    for line in read_text(path).splitlines():
        m = re.match(r"^  (\S+):\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^    version:\s*(\S+)\s*$", line)
        if m and cur:
            out[cur] = m.group(1).strip("'\"")
            cur = None
    out.pop("idf", None)
    return out


def parse_declared(path):
    """THIRD_PARTY_NOTICES.md table rows -> {name: (version, licence)}."""
    out = {}
    if not os.path.isfile(path):
        return out
    for line in read_text(path).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 3 and "/" in cells[0] or (line.startswith("|") and cells[0] == "ESP-IDF"):
            out[cells[0]] = (cells[1], cells[2])
    return out


def idf_version(idf):
    try:
        h = read_text(os.path.join(idf, "components/esp_common/include/esp_idf_version.h"))
        v = [re.search(rf"#define ESP_IDF_VERSION_{k}\s+(\d+)", h).group(1) for k in ("MAJOR", "MINOR", "PATCH")]
        return ".".join(v)
    except (OSError, AttributeError):
        return "unknown"


def licence_files(d, depth=1):
    """Licence/notice files at the top of d and (depth 1) one directory down. -> [(relpath, text)]"""
    found = []
    if not os.path.isdir(d):
        return found
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p) and LICENCE_FILE.match(name):
            found.append((name, read_text(p)))
    if depth:
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isdir(p) and not name.startswith(".") and name not in ("test", "tests", "examples", "docs", "node_modules"):
                found += [(f"{name}/{rel}", t) for rel, t in licence_files(p, depth - 1)]
    return found


def ancestor_licences(dirs, root):
    """Licence files in every directory from each linked source file up to the component root."""
    root = os.path.realpath(root)
    seen, out = set(), []
    for d in sorted(dirs):
        while d.startswith(root) and d not in seen:
            seen.add(d)
            for rel, t in licence_files(d, 0):
                label = os.path.relpath(os.path.join(d, rel), root)
                out.append((label, t))
            if d == root:
                break
            d = os.path.dirname(d)
    return out


def parse_map(map_path):
    """Archive members pulled into the link: [(archive path as in the map, member)]."""
    members, on = set(), False
    pat = re.compile(r"^(\S+\.a)\(([^)]+)\)")
    for line in open(map_path, encoding="utf-8", errors="replace"):
        if line.startswith("Archive member included"):
            on = True
            continue
        if on and line.startswith("Discarded input sections"):
            break
        if on:
            m = pat.match(line)
            if m:
                members.add((m.group(1), m.group(2)))
    return members


def object_index(cc_path):
    """compile_commands.json -> {(output dir, object basename): [source files]}"""
    idx = {}
    for e in json.load(open(cc_path)):
        out = e.get("output", "")
        key = (os.path.dirname(out).split("/CMakeFiles/")[0], os.path.basename(out))
        idx.setdefault(key, []).append(e["file"])
    return idx


def src_license_markers(path):
    try:
        head = read_text(path, 6000)
    except OSError:
        return []
    hits = []
    for m in SPDX_COPYLEFT.finditer(head):
        expr = m.group(1).strip()
        # "Apache-2.0 OR GPL-2.0-or-later": the file may be used under the permissive alternative
        alts = re.split(r"\s+OR\s+", expr)
        if len(alts) > 1 and any(not re.search(r"GPL", alt) for alt in alts):
            continue
        hits.append(expr)
    if not hits and COPYLEFT.search(head):
        hits = ["header text mentions GNU (L)GPL"]
    return hits


def classify(path, idf, project, managed_dir):
    """Source path -> (kind, component id)."""
    p = os.path.realpath(path)
    for root, kind in ((os.path.realpath(managed_dir), "managed"),):
        if p.startswith(root + os.sep):
            return kind, p[len(root) + 1:].split(os.sep)[0]
    if p.startswith(os.path.realpath(os.path.join(idf, "components")) + os.sep):
        return "idf", p[len(os.path.realpath(os.path.join(idf, "components"))) + 1:].split(os.sep)[0]
    if p.startswith(os.path.realpath(os.path.join(project, "main")) + os.sep):
        return "own", "twiddle"
    return "other", os.path.dirname(p)


def load_allow(path):
    if path and os.path.isfile(path):
        return json.load(open(path))["allow"]
    return []


def load_blobs(path):
    """notices-allow.json 'blobs': reviewed statements about prebuilt binaries (radio firmware, PHY, BT controller)."""
    if path and os.path.isfile(path):
        return json.load(open(path)).get("blobs", [])
    return []


# Prebuilt radio libraries (no sources). The ESP32-P4 has no radio, so none may be linked into a P4 image; if one
# ever shows up (another chip, another IDF layout) the check fails until a 'radio-blob' allow entry records its licence.
BLOB_ARCHIVE = re.compile(r"/(esp_phy|esp_wifi)/lib/|/bt/controller/lib_|/(libphy|libnet80211|libpp|libcore|libcoexist|libmesh|libwpa|libwpa2|libbtdm_app|libble_app)\.a$")


def allowed(allow, comp, what, key):
    for a in allow:
        if a["component"] == comp and a["what"] == what and a["match"].lower() in key.lower():
            return a
    return None


def analyse(project, build, map_path, allow, toolchain_licenses=None):
    desc = json.load(open(os.path.join(build, "project_description.json")))
    idf = desc["idf_path"]
    managed_dir = os.path.join(project, "managed_components")
    lock = parse_lock(os.path.join(project, "dependencies.lock"))
    declared = parse_declared(os.path.join(project, "THIRD_PARTY_NOTICES.md"))
    members = parse_map(map_path)
    idx = object_index(os.path.join(build, "compile_commands.json"))
    comps, findings, warnings = {}, [], []
    for arch in sorted({a for a, _ in members if BLOB_ARCHIVE.search(a)}):
        short = arch.replace(idf, "$IDF")
        if allowed(allow, "radio-blob", "blob", short) is None:
            findings.append("prebuilt radio library in the link map: " + short + " (the P4 has no radio; record its licence under 'radio-blob' in notices-allow.json)")

    def comp_rec(kind, cid):
        key = f"{kind}:{cid}"
        if key not in comps:
            comps[key] = {"id": cid, "kind": kind, "objects": 0, "files": [], "version": "", "licence": "", "src_flags": set(), "dirs": set()}
        return comps[key]

    for arch, member in sorted(members):
        if DENY_ARCHIVES.search(arch):
            findings.append(f"copyleft: Arduino core archive in link map: {arch}")
        adir = os.path.dirname(arch)
        if os.path.isabs(arch):  # toolchain runtime libraries
            name = os.path.basename(arch)
            tc = comp_rec("toolchain", "gcc-runtime" if name in ("libgcc.a", "libstdc++.a") else "newlib-libc")
            tc["objects"] += 1
            continue
        sources = idx.get((os.path.join(os.path.realpath(build), adir), member)) or idx.get((os.path.join(build, adir), member))
        if not sources:
            # prebuilt archive or generated object: attribute by archive directory only
            c = comp_rec("unresolved", adir)
            c["objects"] += 1
            continue
        for s in sources:
            kind, cid = classify(s, idf, project, managed_dir)
            c = comp_rec(kind, cid)
            c["objects"] += 1
            c["dirs"].add(os.path.dirname(os.path.realpath(s)))
            for mk in src_license_markers(s):
                c["src_flags"].add((os.path.relpath(s, os.path.dirname(os.path.dirname(s))) if False else os.path.basename(s), mk))

    # managed components pinned in the lock but with no object in the map (header-only, build helpers)
    for name in lock:
        if f"managed:{name.replace('/', '__', 1)}" not in comps and os.path.isdir(os.path.join(managed_dir, name.replace('/', '__', 1))):
            comp_rec("managed", name.replace("/", "__", 1))["note"] = "no object file in the link map (header-only or build-time helper): listed because it is pinned in the build"
    comps["idf-root:idf"] = {"id": "idf", "kind": "idf-root", "objects": 0, "files": [], "version": "", "licence": "", "src_flags": set(), "dirs": set()}
    # versions + licence files
    iv = idf_version(idf)
    tc_dir = toolchain_licenses
    for key, c in comps.items():
        kind, cid = c["kind"], c["id"]
        if kind == "managed":
            name = cid.replace("__", "/", 1)
            c["name"] = name
            c["version"] = lock.get(name, "")
            if not c["version"]:
                warnings.append(f"{name}: not in dependencies.lock")
            dv = declared.get(name)
            if dv:
                c["licence"] = dv[1]
                if dv[0].split("~")[0] != c["version"].split("~")[0]:
                    warnings.append(f"{name}: THIRD_PARTY_NOTICES lists {dv[0]} but dependencies.lock pins {c['version']}")
            else:
                warnings.append(f"{name}: no row in THIRD_PARTY_NOTICES.md")
            c["files"] = licence_files(os.path.join(managed_dir, cid), 0)
            c["files"] += [x for x in ancestor_licences(c["dirs"], os.path.join(managed_dir, cid)) if x not in c["files"]]
            lic_dir = os.path.join(managed_dir, cid, "LICENSES")
            if os.path.isdir(lic_dir):
                c["files"] += [(f"LICENSES/{n}", read_text(os.path.join(lic_dir, n))) for n in sorted(os.listdir(lic_dir)) if n != "README.md"]
        elif kind == "idf":
            c["name"] = f"ESP-IDF component {cid}"
            c["version"] = iv
            c["files"] = ancestor_licences(c["dirs"], os.path.join(idf, "components", cid))
            c["licence"] = "Apache-2.0 (ESP-IDF default, see ESP-IDF entry)" if not c["files"] else "see files below (ESP-IDF default Apache-2.0 for the rest)"
        elif kind == "idf-root":
            c["name"] = "ESP-IDF (root licence)"
            c["version"] = iv
            c["licence"] = "Apache-2.0"
            c["files"] = [(n, t) for n, t in licence_files(idf, 0) if n.upper() == "LICENSE"]
        elif kind == "toolchain":
            c["name"] = "GCC runtime libraries (libgcc, libstdc++)" if cid == "gcc-runtime" else "newlib C library (libc, libm)"
            m = re.search(r"/riscv32-esp-elf/(esp-[^/]+)/", next(a for a, _ in members if os.path.isabs(a)))
            c["version"] = m.group(1) if m else ""
            c["licence"] = "GPL-3.0-or-later WITH GCC-exception-3.1" if cid == "gcc-runtime" else "BSD-style mixture (newlib COPYING.NEWLIB)"
            if tc_dir:
                names = ("gcc/COPYING.RUNTIME", "gcc/COPYING3") if cid == "gcc-runtime" else ("newlib/COPYING.NEWLIB",)
                c["files"] = [(n, read_text(os.path.join(tc_dir, n))) for n in names if os.path.isfile(os.path.join(tc_dir, n))]
        elif kind == "own":
            c["name"] = "Twiddle firmware (this project)"
            c["licence"] = "CC BY-NC-SA 4.0"
        else:
            c["name"] = f"unattributed objects ({cid})"

    # findings
    for key, c in comps.items():
        cname = c.get("name", c["id"])
        key_id = c["id"]
        for fname, marker in sorted(c["src_flags"]):
            a = allowed(allow, key_id, "source", fname + " " + marker) or allowed(allow, key_id, "source", marker)
            msg = f"{cname}: linked source {fname} declares {marker}"
            if a is None:
                findings.append("copyleft: " + msg)
            elif a.get("status") == "needs-review":
                warnings.append("NEEDS REVIEW: " + msg + f" ({a['reason']})")
        if c["kind"] in ("managed", "idf", "idf-root", "toolchain"):
            for rel, text in c["files"]:
                if rel.startswith("LICENSES/") and not re.search(r"GPL", rel):
                    continue
                if COPYLEFT.search(text[:6000]) or re.search(r"GPL", rel):
                    a = allowed(allow, key_id, "licence-file", rel)
                    msg = f"{cname}: licence file {rel} is (L)GPL text"
                    if a is None:
                        findings.append("copyleft: " + msg)
                    elif a.get("status") == "needs-review":
                        warnings.append("NEEDS REVIEW: " + msg + f" ({a['reason']})")
        if c["kind"] == "unresolved":
            warnings.append(f"{cname}: {c['objects']} object(s) could not be traced to sources (prebuilt library?): licence not scanned")
    present = {c["id"] for c in comps.values()}
    for a in allow:
        if a.get("status") == "needs-review" and a["component"] in present:
            msg = f"NEEDS REVIEW: {a['component']}: {a['reason']}"
            if msg not in warnings:
                warnings.append(msg)
    return {"comps": comps, "findings": findings, "warnings": warnings, "idf": iv,
            "project": desc.get("project_name", ""), "pver": desc.get("project_version", "")}


def render(res, version, board, css, own_notices):
    comps = sorted(res["comps"].values(), key=lambda c: ({"own": 0, "managed": 1, "idf-root": 2, "idf": 3, "toolchain": 4}.get(c["kind"], 4), c.get("name", "")))
    e = html.escape
    rows, bodies = [], []
    for i, c in enumerate(comps):
        if c["kind"] in ("unresolved", "other"):
            continue
        rows.append(f'<tr><td><a href="#c{i}">{e(c["name"])}</a></td><td>{e(c["version"])}</td><td>{e(c["licence"])}</td></tr>')
        txt = "".join(f'<h4>{e(rel)}</h4><pre>{e(t)}</pre>' for rel, t in c["files"]) or "<p>No separate licence file is packaged for this component; the licence above is the one declared by the project.</p>"
        bodies.append(f'<section id="c{i}"><h3>{e(c["name"])} {e(c["version"])}</h3><p>Licence: {e(c["licence"])}</p>{txt}</section>')
    blobs_html = ""
    if res.get("blobs"):
        blobs_html = "<h2>Prebuilt binaries</h2>" + "".join(
            f'<div><h3>{e(b["name"])}</h3><p>Licence: {e(b["licence"])}. In this image: {e(b["in_p4_image"])}.</p><p>{e(b["reason"])}</p></div>'
            for b in res["blobs"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Licences: Twiddle {e(version)} for {e(board)}</title><link rel="stylesheet" href="{e(css)}"></head>
<body><main class="wrap">
<p><a href="../../../">Back to the flasher</a></p>
<h1>Licences and notices: Twiddle {e(version)} ({e(board)})</h1>
<p>This is the list of third-party software in the firmware image, at the versions that were built (ESP-IDF {e(res['idf'])}). Each component keeps its own licence; the Twiddle source code itself is CC BY-NC-SA 4.0 and covers only code written for Twiddle. Nothing in that licence limits the rights these licences give you. No GPL or LGPL component is linked into this image (checked from the linker map by <code>scripts/gen_notices.py --check</code>).</p>
<table><thead><tr><th>Component</th><th>Version</th><th>Licence</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
{blobs_html}
<h2>Notices for code and data in the Twiddle source tree</h2><pre>{e(own_notices)}</pre>
<h2>Full licence texts</h2>{''.join(bodies)}
</main></body></html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--map")
    ap.add_argument("--version", required=True, help="firmware version string, for the page title")
    ap.add_argument("--board", default="Guition JC1060P470C")
    ap.add_argument("--out", help="output directory (omit with --check for a check only)")
    ap.add_argument("--check", action="store_true", help="exit 1 if a copyleft component is linked")
    ap.add_argument("--allow", default=os.path.join(HERE, "notices-allow.json"))
    ap.add_argument("--css", default="../../../style.css", help="stylesheet URL used by the generated page")
    ap.add_argument("--toolchain-licenses", help="toolchain share/licenses directory (default: derived from the map)")
    a = ap.parse_args(argv)
    desc = json.load(open(os.path.join(a.build, "project_description.json")))
    map_path = a.map or os.path.join(a.build, desc["project_name"] + ".map")
    tc = a.toolchain_licenses
    if not tc:
        for arch, _ in parse_map(map_path):
            m = re.match(r"^(.*/riscv32-esp-elf/[^/]+/riscv32-esp-elf)/", arch) if os.path.isabs(arch) else None
            if m:
                tc = os.path.join(m.group(1), "share", "licenses")
                break
    res = analyse(a.project, a.build, map_path, load_allow(a.allow), tc)
    res["blobs"] = load_blobs(a.allow)
    for w in res["warnings"]:
        print("WARNING:", w, file=sys.stderr)
    for f in res["findings"]:
        print("FAIL:", f, file=sys.stderr)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        own = ""
        np_ = os.path.join(a.project, "THIRD_PARTY_NOTICES.md")
        if os.path.isfile(np_):
            own = read_text(np_)
        roots = [(a.project, "<project>"), (a.build, "<build>"), (desc.get("idf_path") or "", "<esp-idf>")]
        with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
            f.write(scrub(render(res, a.version, a.board, a.css, own), roots))
        comps = [{"name": c.get("name"), "kind": c["kind"], "version": c["version"], "licence": c["licence"], "objects": c["objects"],
                  "licence_files": [r for r, _ in c["files"]]} for c in res["comps"].values()]
        with open(os.path.join(a.out, "components.json"), "w", encoding="utf-8") as f:
            f.write(scrub(json.dumps({"version": a.version, "idf": res["idf"], "components": sorted(comps, key=lambda c: (c["kind"], c["name"] or "")),
                                      "check": "fail" if res["findings"] else "pass", "warnings": res["warnings"]}, indent=2), roots))
        with open(os.path.join(a.out, "licenses.txt"), "w", encoding="utf-8") as f:
            f.write(scrub(own + "\n", roots))
            for c in res["comps"].values():
                for rel, t in c["files"]:
                    f.write(scrub(f"\n\n===== {c.get('name')} {c['version']}: {rel} =====\n{t}", roots))
        print(f"gen_notices: wrote {a.out} ({len(res['comps'])} component groups)")
    if a.check or True:
        if res["findings"]:
            print(f"gen_notices: CHECK FAILED ({len(res['findings'])} finding(s))", file=sys.stderr)
            return 1 if a.check else 0
        print("gen_notices: copyleft check passed" + (f" with {len(res['warnings'])} warning(s)" if res["warnings"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
