#!/usr/bin/env python3
"""Third-party notices + copyleft (LGPL/GPL) inventory for a PlatformIO / Arduino-ESP32 build of the Twiddle firmware (ESP32-S3).

The P4 image is an ESP-IDF project (scripts/gen_notices.py). The S3 image is built with PlatformIO on the pioarduino
platform: our code + Arduino-ESP32 (core and libraries, built from source into the image, LGPL-2.1) + prebuilt ESP-IDF
libraries (Espressif, mostly Apache-2.0, plus radio blobs) + libraries from lib_deps (LVGL, NimBLE-Arduino ...) + the
toolchain runtime. This script decides what is IN the image from the linker map, not from what is installed.

Reads (read-only):
  --project DIR   firmware checkout (THIRD_PARTY_NOTICES.md, platformio.ini)
  --build DIR     PlatformIO build dir (.pio/build/panel-release): firmware.map; compile_commands.json from
                  `pio run -e panel-release -t compiledb` (default: BUILD/compile_commands.json, then PROJECT/compile_commands.json)
Writes (--out DIR): index.html (licence page, full texts), components.json, licenses.txt

How an input is attributed: every object that contributes bytes to the image (>0 bytes in the memory map) is traced to its
source file through compile_commands.json and so to a group: our own code, Arduino-ESP32 core, Arduino-ESP32 library <name>,
a lib_deps library, or (archives that are prebuilt and have no source here) a prebuilt ESP-IDF library, the GCC runtime, newlib.
Each linked source file's header is scanned for an LGPL/GPL licence marker.

--check exits 1 when
  * a linked source declares GPL or AGPL (not LGPL) and scripts/notices-allow-s3.json has no reviewed entry for it, or
  * a group with LGPL source is not in "lgpl_reviewed" (a new LGPL dependency needs a human decision), or
  * a prebuilt ESP-IDF archive is linked that is neither a source-built IDF library nor listed under "blobs" (new binary blob), or
  * the LGPL-2.1 licence text cannot be found.
The LGPL groups that ARE reviewed are listed on the page with the statement that they are statically linked.
Limits: prebuilt IDF archives cannot be scanned per object (no sources here); their licence comes from the ESP-IDF component
directory when the ESP-IDF source package is installed, else it is marked unverified. Not legal advice. Standard library only.
"""
import argparse
import collections
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_notices as gn  # noqa: E402  (read_text, licence_files, ancestor_licences)

LGPL_RX = re.compile(r"(GNU\s+(Lesser|Library)\s+General\s+Public|\bLGPL)", re.I)
GPL_RX = re.compile(r"(GNU\s+General\s+Public\s+License|GNU\s+Affero|\bA?GPL-)", re.I)
APACHE_RX = re.compile(r"Apache\s+License|Apache-2\.0", re.I)
MIT_RX = re.compile(r"\bMIT\b|Permission is hereby granted, free of charge", re.I)
SPDX_RX = re.compile(r"SPDX-License-Identifier:\s*([^\n*]+)")


def file_licence(path):
    """Licence label of one source file from its header: SPDX expression, else what the text says."""
    try:
        head = gn.read_text(path, 6000)
    except OSError:
        return "unreadable"
    m = SPDX_RX.search(head)
    if m:
        expr = m.group(1).strip().rstrip("*/ ").strip()
        return expr
    if LGPL_RX.search(head):
        return "LGPL (header text)"
    if GPL_RX.search(head):
        return "GPL (header text)"
    if APACHE_RX.search(head):
        return "Apache-2.0 (header text)"
    if MIT_RX.search(head):
        return "MIT (header text)"
    return "no licence header"


def copyleft_kind(label):
    """'lgpl', 'gpl' or None for a licence label; an 'X OR Y' expression with a permissive alternative counts as permissive."""
    alts = re.split(r"\s+OR\s+", label)
    if len(alts) > 1 and any(not re.search(r"GPL", a) for a in alts):
        return None
    if re.search(r"LGPL|Lesser|Library", label):
        return "lgpl"
    if re.search(r"GPL", label):
        return "gpl"
    return None


def parse_map_sizes(map_path):
    """-> {input as written in the map: bytes it contributes to allocated (image) sections}. Handles the one-line and the two-line (long name) form."""
    sizes = collections.Counter()
    on = False
    cur = ""
    one = re.compile(r"^\s+(?:\S+\s+)?0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+(\S.*?)\s*$")
    out_sec = re.compile(r"^(\.[^\s]+)")
    for line in open(map_path, encoding="utf-8", errors="replace"):
        if not on:
            on = line.startswith("Linker script and memory map")
            continue
        ms = out_sec.match(line)
        if ms:
            cur = ms.group(1)
        if cur.startswith((".debug", ".comment", ".xtensa", ".note", ".riscv", ".stab", ".line", ".strtab", ".symtab", ".shstrtab")):
            continue  # not in the flash image
        m = one.match(line)
        if m and (m.group(2).endswith(".o") or m.group(2).endswith(".obj") or m.group(2).endswith(")")):
            sizes[m.group(2)] += int(m.group(1), 16)
    return sizes


def load_compdb(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            idx, by_base = {}, collections.defaultdict(list)
            import json as _j
            for e in _j.load(open(p, encoding="utf-8")):
                out = e.get("output", "")
                f = e["file"] if os.path.isabs(e["file"]) else os.path.join(e.get("directory", ""), e["file"])
                idx[out] = f
                by_base[os.path.basename(out)].append(f)
            return idx, by_base, p
    return None, None, None


def pkg_version(path_json):
    try:
        return json.load(open(path_json)).get("version", "")
    except (OSError, ValueError):
        return ""


def lib_meta(d):
    """(version, declared licence) from a PlatformIO library's library.json / library.properties."""
    ver = lic = ""
    for name in ("library.json", "library.properties"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            t = gn.read_text(p)
            m = re.search(r'"version"\s*:\s*"([^"]+)"', t) or re.search(r"^version=(.+)$", t, re.M)
            ver = ver or (m.group(1).strip() if m else "")
            m = re.search(r'"license"\s*:\s*"([^"]+)"', t) or re.search(r"^license=(.+)$", t, re.M)
            lic = lic or (m.group(1).strip() if m else "")
    return ver, lic


def rec(comps, key, **kw):
    c = comps.setdefault(key, {"id": key, "kind": "", "name": key, "version": "", "licence": "", "objects": 0, "kept": 0,
                               "files": [], "labels": collections.Counter(), "srcs": set(), "dirs": set(), "note": ""})
    c.update({k: v for k, v in kw.items() if v})
    return c


def analyse(project, build, map_path, compdb, allow):
    sizes = parse_map_sizes(map_path)
    idx, by_base, cdb_path = compdb
    if idx is None:
        raise SystemExit("gen_notices_pio: no compile_commands.json (run: pio run -e panel-release -t compiledb)")
    comps, findings, warnings, unresolved = {}, [], [], []
    env = os.path.basename(os.path.normpath(build))
    fw_dir = fwlibs_dir = tc_dir = pio_pkgs = None
    arch_seen = set()
    for inp, size in sizes.items():
        if size <= 0:
            continue
        m = re.match(r"^(.*\.a)\((.*)\)$", inp)
        arch, member = (m.group(1), m.group(2)) if m else (None, None)
        if arch and os.path.isabs(arch):
            arch_seen.add(arch)
            if "/framework-arduinoespressif32-libs/" in arch:
                fwlibs_dir = arch.split("/framework-arduinoespressif32-libs/")[0] + "/framework-arduinoespressif32-libs"
                pio_pkgs = os.path.dirname(fwlibs_dir)
                name = os.path.basename(arch)[3:-2]
                c = rec(comps, "idf:" + name, kind="idf", name="ESP-IDF library " + name)
                c["objects"] += 1
                c["kept"] += size
            elif "/toolchain-" in arch:
                tc_dir = re.sub(r"(/toolchain-[^/]+)/.*", r"\1", arch)
                base = os.path.basename(arch)
                key = "toolchain:gcc-runtime" if base in ("libgcc.a", "libstdc++.a") else "toolchain:newlib"
                c = rec(comps, key, kind="toolchain",
                        name="GCC runtime libraries (libgcc, libstdc++)" if key.endswith("gcc-runtime") else "newlib C library (libc, libm)")
                c["objects"] += 1
                c["kept"] += size
            else:
                unresolved.append(inp)
            continue
        # object in the build tree (our sources, Arduino libraries, lib_deps) or a member of libFrameworkArduino.a
        key = inp if not arch else None
        src = None
        if arch:
            for cand in (os.path.join(os.path.dirname(arch), "FrameworkArduino", member), os.path.join(os.path.dirname(arch), member)):
                src = idx.get(cand)
                if src:
                    break
            if not src and by_base.get(member):
                src = by_base[member][0]
        else:
            src = idx.get(inp)
        if not src:
            unresolved.append(inp)
            continue
        src = os.path.realpath(src)
        p = project
        pr = os.path.realpath(project)
        if src.startswith(pr + os.sep) and "/.pio/" not in src:
            c = rec(comps, "own:twiddle", kind="own", name="Twiddle firmware (this project)", licence="CC BY-NC-SA 4.0")
        elif "/framework-arduinoespressif32/cores/" in src or "/framework-arduinoespressif32/variants/" in src:
            fw_dir = src.split("/framework-arduinoespressif32/")[0] + "/framework-arduinoespressif32"
            c = rec(comps, "arduino:core", kind="arduino", name="Arduino-ESP32 core (libFrameworkArduino)")
        elif "/framework-arduinoespressif32/libraries/" in src:
            fw_dir = src.split("/framework-arduinoespressif32/")[0] + "/framework-arduinoespressif32"
            lib = src.split("/framework-arduinoespressif32/libraries/")[1].split("/")[0]
            c = rec(comps, "arduino:lib:" + lib, kind="arduino", name="Arduino-ESP32 library " + lib)
            c["dirs"].add(os.path.join(fw_dir, "libraries", lib))
        elif "/libdeps/" in src:
            rest = src.split("/libdeps/")[1].split("/")
            lib = rest[1]
            c = rec(comps, "dep:" + lib, kind="dep", name=lib)
            c["dirs"].add(os.path.join(src.split("/libdeps/")[0], "libdeps", rest[0], lib))
        else:
            c = rec(comps, "other:" + os.path.dirname(src), kind="other", name="unattributed " + os.path.dirname(src))
        c["objects"] += 1
        c["kept"] += size
        if src not in c["srcs"]:
            c["srcs"].add(src)
            lab = file_licence(src)
            if c["kind"] == "arduino" and lab == "no licence header":
                lab = "LGPL-2.1-or-later (package default, no file header)"  # framework package.json: LGPL-2.1-or-later; be conservative
            c["labels"][lab] += 1
    # --- versions and licence texts ---
    for c in comps.values():
        k = c["kind"]
        if k == "arduino":
            c["version"] = pkg_version(os.path.join(fw_dir, "package.json")) if fw_dir else ""
        elif k == "dep":
            d = next(iter(c["dirs"]), "")
            c["version"], declared = lib_meta(d)
            c["files"] = gn.licence_files(d, 0)
            c["licence"] = declared or "see the licence files below (no licence field in the library metadata)"
        elif k == "idf":
            c["version"] = "ESP-IDF 5.5.x prebuilt (%s)" % (pkg_version(os.path.join(fwlibs_dir, "package.json")) if fwlibs_dir else "")
        elif k == "toolchain":
            mm = re.search(r"toolchain-xtensa-esp-elf", tc_dir or "")
            c["version"] = "xtensa-esp-elf " + next((re.search(r"/gcc/xtensa-esp-elf/([0-9.]+)/", a).group(1) for a in arch_seen if "/gcc/xtensa-esp-elf/" in a), "")
    # --- classification of Arduino groups ---
    lgpl_groups, gpl_hits = [], []
    for c in comps.values():
        if c["kind"] not in ("arduino", "dep", "own"):
            continue
        kinds = collections.Counter()
        for lab, n in c["labels"].items():
            kinds[copyleft_kind(lab) or "other"] += n
        c["lgpl_files"] = kinds["lgpl"]
        c["gpl_files"] = kinds["gpl"]
        if c["kind"] == "arduino":
            c["licence"] = "LGPL-2.1-or-later for %d of %d linked source files; the rest: %s" % (
                kinds["lgpl"], sum(kinds.values()), ", ".join("%s (%d)" % (l, n) for l, n in sorted(c["labels"].items()) if not copyleft_kind(l)) or "none")
        if kinds["lgpl"]:
            lgpl_groups.append(c["id"])
        if kinds["gpl"]:
            gpl_hits.append(c)
    # --- findings ---
    reviewed = {x["group"]: x for x in allow.get("lgpl_reviewed", [])}
    for gid in lgpl_groups:
        if gid not in reviewed:
            findings.append("copyleft: LGPL source linked in %s and no 'lgpl_reviewed' entry for it" % gid)
    for c in gpl_hits:
        ok = [a for a in allow.get("gpl_reviewed", []) if a["group"] == c["id"]]
        if not ok:
            findings.append("copyleft: GPL/AGPL source declared in linked files of %s: %s" % (
                c["name"], ", ".join(sorted(l for l in c["labels"] if copyleft_kind(l) == "gpl"))))
    blobs = {b["archive"]: b for b in allow.get("blobs", [])}
    managed = allow.get("idf_managed", {})
    idf_src = os.path.join(pio_pkgs or "", "framework-espidf")
    alias = allow.get("idf_component_alias", {})
    ok_cl = {(x["component"], x["label"]): x for x in allow.get("idf_copyleft_reviewed", [])}
    for gid, c in comps.items():
        if c["kind"] != "idf":
            continue
        name = gid[4:]
        cdir = os.path.join(idf_src, "components", alias.get(name, name))
        if name in blobs:
            c["licence"] = blobs[name]["licence"]
            c["note"] = "prebuilt binary (no source here): " + blobs[name]["what"]
            c["blob"] = True
        elif name in managed:
            c["licence"] = managed[name]["licence"] + " (declared upstream; NOT verified locally: the component's sources are not in the ESP-IDF package)"
            c["version"] = managed[name].get("version", c["version"])
        elif os.path.isdir(cdir):
            labels = collections.Counter()
            n_files = 0
            for dp, dns, fns in os.walk(cdir):
                dns[:] = [d for d in dns if d not in ("test", "tests", "examples", "docs", ".git", "host_test", "linux")]
                for fn in fns:
                    if fn.endswith((".c", ".h", ".cpp", ".S", ".cc", ".hpp")):
                        n_files += 1
                        labels[file_licence(os.path.join(dp, fn))] += 1
            c["labels"] = labels
            top = [l for l, _ in labels.most_common() if l not in ("no licence header", "unreadable")][:3]
            c["licence"] = "%s (scanned %d source files of the ESP-IDF component, not only the linked ones)" % (", ".join(top) or "Apache-2.0 (ESP-IDF default)", n_files)
            c["files"] = gn.licence_files(cdir, 0)
            for lab in labels:
                kind = copyleft_kind(lab)
                if kind and (alias.get(name, name), lab) not in ok_cl:
                    findings.append("copyleft: ESP-IDF component %s has source files declaring %s (%d files); the archive is linked. "
                                    "Review and add an 'idf_copyleft_reviewed' entry with a reason" % (alias.get(name, name), lab, labels[lab]))
        else:
            findings.append("new prebuilt ESP-IDF library in the link map with no reviewed licence entry: lib%s.a "
                            "(add it to 'blobs' or 'idf_managed' in notices-allow-s3.json after reading its licence)" % name)
            c["licence"] = "NOT REVIEWED"
    for u in unresolved:
        warnings.append("input could not be traced to a source or known archive: " + u)
    return {"comps": comps, "findings": findings, "warnings": warnings, "lgpl_groups": sorted(lgpl_groups),
            "fw_dir": fw_dir, "fwlibs_dir": fwlibs_dir, "tc_dir": tc_dir, "pio_pkgs": pio_pkgs, "compdb": cdb_path,
            "reviewed": reviewed, "env": env}


def find_text(res, what):
    """Full licence texts we ship: returns (label, text) or None."""
    tc = res["tc_dir"]
    cands = {
        "LGPL-2.1": [os.path.join(tc or "", "share/licenses/gcc/COPYING.LIB"), os.path.join(tc or "", "share/licenses/newlib/COPYING.LIB")],
        "GPL-3.0": [os.path.join(tc or "", "share/licenses/gcc/COPYING3")],
        "GCC-exception": [os.path.join(tc or "", "share/licenses/gcc/COPYING.RUNTIME")],
        "newlib": [os.path.join(tc or "", "share/licenses/newlib/COPYING.NEWLIB")],
        "Apache-2.0": [os.path.join(os.path.dirname(res["pio_pkgs"] or "") , "x"), ],
    }
    for p in cands.get(what, []):
        if os.path.isfile(p):
            t = gn.read_text(p, 200000)
            if what == "LGPL-2.1" and "Version 2.1, February 1999" not in t:
                continue
            return os.path.relpath(p, tc) if tc else p, t
    return None


def render(res, version, board, css, own_notices, lgpl_text, extra_texts, assets):
    e = html.escape
    comps = sorted(res["comps"].values(), key=lambda c: ({"own": 0, "arduino": 1, "dep": 2, "idf": 3, "toolchain": 4}.get(c["kind"], 5), c["name"]))
    rows = []
    for c in comps:
        if c["kind"] in ("other",):
            continue
        extra = ""
        if c["kind"] == "arduino":
            extra = " Statically linked: %d object(s), %d bytes in the image." % (c["objects"], c["kept"])
        rows.append("<tr><td>%s</td><td>%s</td><td>%s%s</td></tr>" % (e(c["name"]), e(c["version"]), e(c["licence"]), e(extra)))
    lgpl_rows = "".join(
        "<li><b>%s</b> %s: %d linked source file(s) under LGPL-2.1-or-later, %d object(s), %d bytes in the image.</li>" % (
            e(res["comps"][g]["name"]), e(res["comps"][g]["version"]), res["comps"][g]["lgpl_files"], res["comps"][g]["objects"], res["comps"][g]["kept"])
        for g in res["lgpl_groups"])
    blob_html = "".join(
        "<li><b>%s</b>: %s. %s</li>" % (e(c["name"]), e(c["licence"]), e(c["note"])) for c in comps if c.get("blob"))
    bodies = []
    for c in comps:
        if c["files"]:
            bodies.append("<section><h3>%s %s</h3><p>Licence: %s</p>%s</section>" % (
                e(c["name"]), e(c["version"]), e(c["licence"]), "".join("<h4>%s</h4><pre>%s</pre>" % (e(r), e(t)) for r, t in c["files"])))
    texts = "".join("<section><h3>%s</h3><pre>%s</pre></section>" % (e(label), e(t)) for label, t in extra_texts)
    asset_li = "".join("<li><code>%s</code>: %s</li>" % (e(n), e(d)) for n, d in assets)
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Licences: Twiddle %(v)s for %(b)s</title><link rel="stylesheet" href="%(css)s"></head>
<body><main class="wrap">
<p><a href="../../../">Back to the flasher</a></p>
<h1>Licences and notices: Twiddle %(v)s (%(b)s)</h1>
<p><strong>This firmware image contains LGPL-2.1 software, statically linked: Arduino-ESP32 (the Arduino core for the ESP32 and its bundled libraries).</strong>
The Twiddle source code is CC BY-NC-SA 4.0 and covers only code written for Twiddle; every other component keeps its own licence.
Nothing in the Twiddle licence limits the rights the LGPL gives you for the LGPL-licensed parts. This list was generated from the linker map of the image
(<code>scripts/gen_notices_pio.py</code>): it names what is in the file you flash, not everything installed on the build machine.</p>
<p><em>Draft wording: this page has not had a legal review.</em></p>
<h2>LGPL-2.1 components in this image</h2>
<ul>%(lgpl)s</ul>
<h2>Your rights, and the corresponding source</h2>
<p>You may modify these LGPL components and the Twiddle source and rebuild the image for your own use, and you may reverse-engineer the firmware to debug such changes. The release provides the material to rebuild and relink the image against a modified Arduino-ESP32 (see <code>REBUILD.md</code> in the source archive) and a written offer for the source. Files published with this release:</p>
<ul>%(assets)s</ul>
<h2>All components in the image</h2>
<table><thead><tr><th>Component</th><th>Version</th><th>Licence</th></tr></thead><tbody>%(rows)s</tbody></table>
<h2>Prebuilt binaries</h2>
<p>These Espressif libraries are linked as binaries without source (the Wi-Fi, PHY, coexistence and Bluetooth-controller firmware). What was and was not verified about their licence:</p>
<ul>%(blobs)s</ul>
<h2>Notices for code and data in the Twiddle source tree</h2><pre>%(own)s</pre>
<h2>Licence texts</h2>%(texts)s%(bodies)s
</main></body></html>
""" % {"v": e(version), "b": e(board), "css": e(css), "lgpl": lgpl_rows, "assets": asset_li, "rows": "".join(rows), "blobs": blob_html,
       "own": e(own_notices), "texts": texts, "bodies": "".join(bodies)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--map")
    ap.add_argument("--compdb")
    ap.add_argument("--version", required=True)
    ap.add_argument("--board", default="Guition JC8048W550C")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--allow", default=os.path.join(HERE, "notices-allow-s3.json"))
    ap.add_argument("--css", default="../../../style.css")
    ap.add_argument("--assets", help="JSON file: [[name, description], ...] of the LGPL release assets listed on the page")
    a = ap.parse_args(argv)
    map_path = a.map or os.path.join(a.build, "firmware.map")
    allow = json.load(open(a.allow)) if os.path.isfile(a.allow) else {}
    cdb = load_compdb(a.compdb, os.path.join(a.build, "compile_commands.json"), os.path.join(a.project, "compile_commands.json"))
    res = analyse(a.project, a.build, map_path, cdb, allow)
    if "own:twiddle" in res["comps"]:
        res["comps"]["own:twiddle"]["version"] = a.version
    lgpl = find_text(res, "LGPL-2.1")
    if res["lgpl_groups"] and not lgpl:
        res["findings"].append("the LGPL-2.1 licence text was not found (looked in the toolchain package share/licenses/gcc/COPYING.LIB)")
    for w in res["warnings"]:
        print("WARNING:", w, file=sys.stderr)
    for f in res["findings"]:
        print("FAIL:", f, file=sys.stderr)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        np_ = os.path.join(a.project, "THIRD_PARTY_NOTICES.md")
        own = gn.read_text(np_) if os.path.isfile(np_) else ""
        extra = []
        if lgpl:
            extra.append(("GNU Lesser General Public License, version 2.1 (text from the toolchain package: %s)" % lgpl[0], lgpl[1]))
        for what, label in (("GPL-3.0", "GNU GPL v3 (libgcc/libstdc++, with the GCC Runtime Library Exception below)"),
                            ("GCC-exception", "GCC Runtime Library Exception 3.1"), ("newlib", "newlib COPYING.NEWLIB")):
            t = find_text(res, what)
            if t:
                extra.append((label, t[1]))
        apache = os.path.join(res["pio_pkgs"] or "", "framework-espidf", "LICENSE")
        if os.path.isfile(apache):
            extra.append(("Apache License 2.0 (ESP-IDF LICENSE; Espressif's prebuilt libraries)", gn.read_text(apache)))
        assets = json.load(open(a.assets)) if a.assets else []
        roots = [(a.project, "<project>"), (a.build, "<build>"), (res["pio_pkgs"] or "", "<platformio>/packages")]
        with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
            f.write(gn.scrub(render(res, a.version, a.board, a.css, own, lgpl, extra, assets), roots))
        comps = [{"name": c["name"], "kind": c["kind"], "version": c["version"], "licence": c["licence"], "objects": c["objects"],
                  "bytes_in_image": c["kept"], "lgpl_source_files": c.get("lgpl_files", 0), "labels": dict(c["labels"]),
                  "sources": sorted(c["srcs"])} for c in res["comps"].values() if c["kind"] != "other"]
        with open(os.path.join(a.out, "components.json"), "w", encoding="utf-8") as f:
            f.write(gn.scrub(json.dumps({"version": a.version, "lgpl_groups": res["lgpl_groups"], "check": "fail" if res["findings"] else "pass",
                                         "warnings": res["warnings"], "findings": res["findings"], "components": sorted(comps, key=lambda c: (c["kind"], c["name"]))}, indent=2), roots))
        with open(os.path.join(a.out, "licenses.txt"), "w", encoding="utf-8") as f:
            f.write(gn.scrub(own + "\n", roots))
            for label, t in extra:
                f.write(gn.scrub("\n\n===== %s =====\n%s" % (label, t), roots))
            for c in res["comps"].values():
                for rel, t in c["files"]:
                    f.write(gn.scrub("\n\n===== %s %s: %s =====\n%s" % (c["name"], c["version"], rel, t), roots))
        print("gen_notices_pio: wrote %s (%d component groups)" % (a.out, len(res["comps"])))
    if res["findings"]:
        print("gen_notices_pio: CHECK FAILED (%d finding(s))" % len(res["findings"]), file=sys.stderr)
        return 1 if a.check else 0
    print("gen_notices_pio: check passed; statically linked LGPL groups: %s" % ", ".join(res["lgpl_groups"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
