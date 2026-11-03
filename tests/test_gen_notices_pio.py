"""gen_notices_pio.py on a miniature PlatformIO layout: our code, an Arduino-ESP32 LGPL library, a lib_deps library, a prebuilt IDF archive."""
import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gen_notices_pio  # noqa: E402

LGPL_HDR = "/* Copyright. This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser\n General Public License as published by the Free Software Foundation; either version 2.1 of the License, or (at your option) any later version. */\n"
LGPL_TEXT = "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1, February 1999\n"
APACHE = "Apache License\nVersion 2.0\n"


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.proj = os.path.join(root, "proj")
        self.build = os.path.join(self.proj, ".pio/build/panel-release")
        self.pkgs = os.path.join(root, "pkgs")
        fw = os.path.join(self.pkgs, "framework-arduinoespressif32")
        w(os.path.join(fw, "package.json"), json.dumps({"version": "3.3.11"}))
        w(os.path.join(fw, "libraries/WebServer/src/WebServer.cpp"), LGPL_HDR)
        w(os.path.join(fw, "cores/esp32/Print.cpp"), "// SPDX-License-Identifier: Apache-2.0\n")
        w(os.path.join(self.pkgs, "framework-arduinoespressif32-libs/package.json"), json.dumps({"version": "5.5.5"}))
        w(os.path.join(self.pkgs, "framework-espidf/LICENSE"), APACHE)
        w(os.path.join(self.pkgs, "framework-espidf/components/lwip/x.c"), "// SPDX-License-Identifier: BSD-3-Clause\n")
        w(os.path.join(self.pkgs, "toolchain-xtensa-esp-elf/share/licenses/gcc/COPYING.LIB"), LGPL_TEXT)
        w(os.path.join(self.proj, ".pio/libdeps/panel-release/lvgl/library.json"), json.dumps({"version": "9.5.0", "license": "MIT"}))
        w(os.path.join(self.proj, ".pio/libdeps/panel-release/lvgl/src/lv.c"), "// SPDX-License-Identifier: MIT\n")
        w(os.path.join(self.proj, "src/main.cpp"), "int x;\n")
        self.cc = [
            {"directory": self.proj, "file": os.path.join(fw, "libraries/WebServer/src/WebServer.cpp"), "output": ".pio/build/panel-release/libabc/WebServer/WebServer.cpp.o"},
            {"directory": self.proj, "file": os.path.join(fw, "cores/esp32/Print.cpp"), "output": ".pio/build/panel-release/FrameworkArduino/Print.cpp.o"},
            {"directory": self.proj, "file": ".pio/libdeps/panel-release/lvgl/src/lv.c", "output": ".pio/build/panel-release/libdef/lvgl/src/lv.c.o"},
            {"directory": self.proj, "file": os.path.join(self.proj, "src/main.cpp"), "output": ".pio/build/panel-release/src/main.cpp.o"},
        ]
        self.map_lines = [
            ".text.a\n                0x42000000       0x100 .pio/build/panel-release/libabc/WebServer/WebServer.cpp.o\n",
            ".text.b\n                0x42000100        0x50 .pio/build/panel-release/libFrameworkArduino.a(Print.cpp.o)\n",
            ".text.c\n                0x42000200        0x80 .pio/build/panel-release/libdef/lvgl/src/lv.c.o\n",
            ".text.d\n                0x42000300        0x20 .pio/build/panel-release/src/main.cpp.o\n",
            ".text.e\n                0x42000400        0x30 %s/framework-arduinoespressif32-libs/esp32s3/lib/liblwip.a(sockets.c.obj)\n" % self.pkgs,
            ".text.f\n                0x42000500        0x30 %s/toolchain-xtensa-esp-elf/bin/../lib/gcc/xtensa-esp-elf/14.2.0/esp32s3/libgcc.a(x.o)\n" % self.pkgs,
        ]
        self.extra_debug = ""
        self.allow = {"lgpl_reviewed": [{"group": "arduino:lib:WebServer", "reason": "test"}], "blobs": [], "idf_managed": {}}
        self.write()

    def write(self):
        json.dump(self.cc, open(os.path.join(self.root, "cc.json"), "w"))
        w(os.path.join(self.build, "firmware.map"), "Memory map\n\nLinker script and memory map\n\n" + "".join(self.map_lines) + self.extra_debug)
        json.dump(self.allow, open(os.path.join(self.root, "allow.json"), "w"))

    def run(self, out=None, *extra):
        args = ["--project", self.proj, "--build", self.build, "--compdb", os.path.join(self.root, "cc.json"), "--version", "1.0.0",
                "--allow", os.path.join(self.root, "allow.json"), "--check", *extra]
        if out:
            args += ["--out", out]
        return gen_notices_pio.main(args)


class PioNoticesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.f = Fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_reviewed_lgpl_passes_and_is_listed(self):
        out = os.path.join(self.tmp, "o")
        self.assertEqual(self.f.run(out), 0)
        d = json.load(open(os.path.join(out, "components.json")))
        self.assertEqual(d["lgpl_groups"], ["arduino:lib:WebServer"])  # the Apache core file and MIT lvgl are not LGPL
        html = open(os.path.join(out, "index.html")).read()
        self.assertIn("contains LGPL-2.1 software, statically linked", html)
        self.assertIn("Version 2.1, February 1999", html)  # full LGPL text is on the page
        self.assertIn("Draft wording", html)

    def test_new_lgpl_group_fails(self):
        self.f.allow["lgpl_reviewed"] = []
        self.f.write()
        self.assertEqual(self.f.run(), 1)

    def test_gpl_source_fails(self):
        w(os.path.join(self.tmp, "proj/.pio/libdeps/panel-release/lvgl/src/lv.c"), "// SPDX-License-Identifier: GPL-2.0-only\n")
        self.assertEqual(self.f.run(), 1)

    def test_dual_licence_with_permissive_option_passes(self):
        w(os.path.join(self.tmp, "proj/.pio/libdeps/panel-release/lvgl/src/lv.c"), "// SPDX-License-Identifier: Apache-2.0 OR GPL-2.0-or-later\n")
        self.assertEqual(self.f.run(), 0)

    def test_unknown_prebuilt_idf_archive_fails(self):
        self.f.map_lines.append(".text.g\n                0x42000600        0x30 %s/framework-arduinoespressif32-libs/esp32s3/lib/libmystery.a(m.o)\n" % self.f.pkgs)
        self.f.write()
        self.assertEqual(self.f.run(), 1)
        self.f.allow["blobs"] = [{"archive": "mystery", "what": "test blob", "licence": "Apache-2.0 per README"}]
        self.f.write()
        self.assertEqual(self.f.run(), 0)

    def test_debug_sections_do_not_count(self):
        # an object that only has debug info (no allocated bytes) is not "in the image"
        self.f.map_lines = [l for l in self.f.map_lines if "lv.c.o" not in l]
        self.f.extra_debug = ".debug_info\n                0x00000000     0x9999 .pio/build/panel-release/libdef/lvgl/src/lv.c.o\n"
        self.f.write()
        out = os.path.join(self.tmp, "o")
        self.assertEqual(self.f.run(out), 0)
        names = [c["name"] for c in json.load(open(os.path.join(out, "components.json")))["components"]]
        self.assertNotIn("lvgl", names)

    def test_missing_lgpl_text_fails(self):
        os.remove(os.path.join(self.tmp, "pkgs/toolchain-xtensa-esp-elf/share/licenses/gcc/COPYING.LIB"))
        self.assertEqual(self.f.run(), 1)


if __name__ == "__main__":
    unittest.main()
