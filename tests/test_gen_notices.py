import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gen_notices  # noqa: E402

APACHE = "Apache License\nVersion 2.0, January 2004\n"
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n"


class Fixture:
    """A miniature ESP-IDF project: one IDF component, one managed component, our main."""

    def __init__(self, root):
        self.root = root
        self.project = os.path.join(root, "proj")
        self.build = os.path.join(self.project, "build")
        self.idf = os.path.join(root, "idf")
        self.write(os.path.join(self.idf, "LICENSE"), APACHE)
        self.write(os.path.join(self.idf, "components/esp_common/include/esp_idf_version.h"),
                   "#define ESP_IDF_VERSION_MAJOR 5\n#define ESP_IDF_VERSION_MINOR 5\n#define ESP_IDF_VERSION_PATCH 1\n")
        self.write(os.path.join(self.idf, "components/log/log.c"), "// SPDX-License-Identifier: Apache-2.0\n")
        self.write(os.path.join(self.project, "managed_components/acme__widget/widget.c"), "// SPDX-License-Identifier: MIT\n")
        self.write(os.path.join(self.project, "managed_components/acme__widget/LICENSE"), "MIT License\n")
        self.write(os.path.join(self.project, "main/main.c"), "int main;\n")
        self.write(os.path.join(self.project, "dependencies.lock"),
                   "dependencies:\n  acme/widget:\n    component_hash: x\n    dependencies:\n    - name: idf\n      version: '>=5'\n    version: 1.0.0\n  idf:\n    version: 5.5.1\n")
        self.write(os.path.join(self.project, "THIRD_PARTY_NOTICES.md"),
                   "| Component | Version | Licence | Source |\n|---|---|---|---|\n| acme/widget | 1.0.0 | MIT | https://example.invalid |\n")
        self.write(os.path.join(self.build, "project_description.json"), json.dumps({"project_name": "fw", "idf_path": self.idf, "project_version": "t"}))
        self.cc, self.members = [], []
        self.add_obj("log", os.path.join(self.idf, "components/log/log.c"), "log.c.obj")
        self.add_obj("acme__widget", os.path.join(self.project, "managed_components/acme__widget/widget.c"), "widget.c.obj")
        self.add_obj("main", os.path.join(self.project, "main/main.c"), "main.c.obj")
        self.finish()

    @staticmethod
    def write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def add_obj(self, comp, src, member):
        out = os.path.join(self.build, f"esp-idf/{comp}/CMakeFiles/__idf_{comp}.dir/{member}")
        self.cc.append({"directory": self.build, "command": "gcc", "file": src, "output": out})
        self.members.append(f"esp-idf/{comp}/lib{comp}.a({member})")

    def finish(self, extra_map=""):
        self.write(os.path.join(self.build, "compile_commands.json"), json.dumps(self.cc))
        body = "".join(f"{m}\n                              (sym)\n" for m in self.members)
        self.write(os.path.join(self.build, "fw.map"), "Archive member included to satisfy reference by file (symbol)\n\n" + body + extra_map + "\nDiscarded input sections\n")

    def run(self, allow=None, out=None):
        ap = os.path.join(self.root, "allow.json")
        json.dump({"allow": allow or []}, open(ap, "w"))
        args = ["--project", self.project, "--build", self.build, "--version", "1.0.0", "--check", "--allow", ap]
        if out:
            args += ["--out", out]
        return gen_notices.main(args)


class NoticesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fx = Fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_clean_build_passes_and_page_is_written(self):
        out = os.path.join(self.tmp, "out")
        self.assertEqual(self.fx.run(out=out), 0)
        page = open(os.path.join(out, "index.html")).read()
        self.assertIn("acme/widget", page)
        self.assertIn("MIT License", page)
        self.assertIn("Apache License", page)  # ESP-IDF root licence text
        comps = json.load(open(os.path.join(out, "components.json")))
        self.assertEqual(comps["check"], "pass")
        self.assertEqual(comps["idf"], "5.5.1")

    def test_arduino_archive_in_map_fails(self):
        self.fx.finish("esp-idf/arduino-esp32/libFrameworkArduino.a(WiFi.cpp.obj)\n")
        self.assertEqual(self.fx.run(), 1)

    def test_prebuilt_radio_library_fails_until_recorded(self):
        self.fx.finish("/x/idf/components/esp_phy/lib/esp32c6/libphy.a(phy_init.o)\n")
        self.assertEqual(self.fx.run(), 1)
        ok = [{"component": "radio-blob", "what": "blob", "match": "esp_phy/lib/esp32c6/libphy.a", "status": "reviewed", "reason": "test"}]
        self.assertEqual(self.fx.run(allow=ok), 0)

    def test_blobs_section_is_rendered(self):
        ap = os.path.join(self.tmp, "allow2.json")
        json.dump({"allow": [], "blobs": [{"name": "Radio blob X", "licence": "Apache-2.0", "in_p4_image": "none", "reason": "because"}]}, open(ap, "w"))
        out = os.path.join(self.tmp, "out2")
        self.assertEqual(gen_notices.main(["--project", self.fx.project, "--build", self.fx.build, "--version", "1", "--check", "--allow", ap, "--out", out]), 0)
        self.assertIn("Radio blob X", open(os.path.join(out, "index.html")).read())

    def test_gpl_source_fails(self):
        self.fx.write(os.path.join(self.fx.idf, "components/log/log.c"), "// SPDX-License-Identifier: GPL-2.0-only\n")
        self.assertEqual(self.fx.run(), 1)

    def test_lgpl_source_fails(self):
        self.fx.write(os.path.join(self.fx.idf, "components/log/log.c"), "/* SPDX-License-Identifier: LGPL-2.1-or-later */\n")
        self.assertEqual(self.fx.run(), 1)

    def test_header_text_gpl_fails(self):
        self.fx.write(os.path.join(self.fx.idf, "components/log/log.c"), "/* This file is free software under the GNU General Public License */\n")
        self.assertEqual(self.fx.run(), 1)

    def test_dual_licence_with_permissive_option_passes(self):
        self.fx.write(os.path.join(self.fx.idf, "components/log/log.c"), "// SPDX-License-Identifier: Apache-2.0 OR GPL-2.0-or-later\n")
        self.assertEqual(self.fx.run(), 0)

    def test_gpl_licence_file_in_managed_component_fails(self):
        self.fx.write(os.path.join(self.fx.project, "managed_components/acme__widget/LICENSE"), GPL)
        self.assertEqual(self.fx.run(), 1)

    def test_allowlist_with_reason_rescues_exact_finding_only(self):
        self.fx.write(os.path.join(self.fx.project, "managed_components/acme__widget/LICENSE"), GPL)
        ok = [{"component": "acme__widget", "what": "licence-file", "match": "LICENSE", "status": "reviewed", "reason": "test"}]
        self.assertEqual(self.fx.run(allow=ok), 0)
        wrong = [{"component": "other", "what": "licence-file", "match": "LICENSE", "status": "reviewed", "reason": "test"}]
        self.assertEqual(self.fx.run(allow=wrong), 1)

    def test_unlisted_gpl_in_unrelated_unlinked_component_is_ignored(self):
        # a GPL file in a component whose objects are not in the map does not count
        self.fx.write(os.path.join(self.fx.idf, "components/other/x.c"), "// SPDX-License-Identifier: GPL-3.0-only\n")
        self.assertEqual(self.fx.run(), 0)

    def test_version_parse_from_lock(self):
        lock = gen_notices.parse_lock(os.path.join(self.fx.project, "dependencies.lock"))
        self.assertEqual(lock, {"acme/widget": "1.0.0"})


class ScrubTests(unittest.TestCase):
    def test_scrub_makes_paths_relative(self):
        roots = [("/home/al/code/fw", "<project>"), ("/home/al/.platformio/packages", "<platformio>/packages")]
        out = gen_notices.scrub('["/home/al/code/fw/main/a.c", "/home/al/.platformio/packages/x/y.c", "/home/al/other", "/tmp/claude-1000/z"]', roots)
        self.assertEqual(out, '["<project>/main/a.c", "<platformio>/packages/x/y.c", "<home>/other", "<home>/z"]')
        self.assertNotIn("/home/", out)


if __name__ == "__main__":
    unittest.main()
