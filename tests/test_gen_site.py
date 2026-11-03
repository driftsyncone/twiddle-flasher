import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gen_site  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
BOARD = "guition-jc1060p470c"
LAYOUT = {"bootloader": 8192, "partition-table": 32768, "otadata": 61440, "app": 131072}


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Release:
    """Builds a fake release directory on disk."""

    def __init__(self, root, version="2.0.0", tested=True):
        self.dir = os.path.join(root, version)
        os.makedirs(self.dir)
        self.version = version
        self.blobs = {n: (n.encode() + b"-data-" + version.encode()) * 50 for n in LAYOUT}
        self.parts = []
        for n, off in LAYOUT.items():
            fn = f"twiddle-p4-{version}-{n}.bin"
            with open(os.path.join(self.dir, fn), "wb") as f:
                f.write(self.blobs[n])
            self.parts.append({"name": n, "offset": off, "file": fn, "size": len(self.blobs[n]), "sha256": sha(self.blobs[n])})
        self.write_parts()
        if tested:
            self.write_tested()

    def write_parts(self, **over):
        pj = {"schema": 1, "board": BOARD, "version": self.version, "chipFamily": "ESP32-P4",
              "flash": {"mode": "dio", "freq": "80m", "size": "16MB"}, "parts": self.parts}
        pj.update(over)
        with open(os.path.join(self.dir, f"twiddle-p4-{self.version}.parts.json"), "w") as f:
            json.dump(pj, f)

    def write_tested(self, **over):
        t = {"schema": 1, "version": self.version, "tested": [{
            "board": BOARD, "chip_rev": "v1.3", "date": "2026-11-10", "tester": "maintainer",
            "app_sha256": sha(self.blobs["app"]), "variants_tested": ["V2", "_I_W_Y"],
            "checklist": {"boots": True, "setup_portal": True, "wifi_join": True, "ota_from_previous": True}}]}
        t.update(over)
        with open(os.path.join(self.dir, "tested.json"), "w") as f:
            json.dump(t, f)


class GenSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rel = os.path.join(self.tmp, "releases")
        os.makedirs(self.rel)
        self.out = os.path.join(self.tmp, "site")
        self.boards = os.path.join(ROOT, "boards.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_gen(self, *extra):
        return gen_site.main(["--releases", self.rel, "--boards", self.boards, "--out", self.out, *extra])

    def test_happy_path(self):
        r = Release(self.rel)
        self.assertEqual(self.run_gen(), 0)
        base = os.path.join(self.out, "fw", BOARD, "2.0.0")
        new = json.load(open(os.path.join(base, "manifest-new.json")))
        upd = json.load(open(os.path.join(base, "manifest-update.json")))
        b = new["builds"][0]
        self.assertEqual(b["chipFamily"], "ESP32-P4")
        self.assertEqual(b["serialType"], "cdc")
        self.assertEqual([(p["offset"]) for p in b["parts"]], [8192, 32768, 61440, 131072])
        self.assertTrue(all(isinstance(p["offset"], int) for p in b["parts"]))
        self.assertTrue(new["new_install_prompt_erase"])
        self.assertTrue(upd["new_install_prompt_erase"])  # false/absent makes esp-web-tools erase silently
        self.assertEqual(sorted(p["offset"] for p in upd["builds"][0]["parts"]), [61440, 131072])
        # nothing in the update manifest touches NVS (0x9000 = 36864) or the bootloader/table
        for p in upd["builds"][0]["parts"]:
            self.assertFalse(36864 <= p["offset"] < 36864 + 24576 and p["offset"] != 61440)
        sums = open(os.path.join(base, "SHA256SUMS")).read()
        for p in r.parts:
            self.assertIn(f"{p['sha256']}  {p['file']}", sums)
        idx = json.load(open(os.path.join(self.out, "index.json")))
        p4 = next(x for x in idx["boards"] if x["id"] == BOARD)
        self.assertEqual(p4["latest"], "2.0.0")
        self.assertEqual(p4["versions"][0]["manifest_new"], f"fw/{BOARD}/2.0.0/manifest-new.json")
        wave = next(x for x in idx["boards"] if x["status"] == "unavailable")
        self.assertEqual(wave["versions"], [])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "fw", BOARD, "latest.json")))

    def test_refuses_without_tested_json(self):
        Release(self.rel, tested=False)
        self.assertEqual(self.run_gen(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "index.json")))

    def test_refuses_when_board_not_listed(self):
        r = Release(self.rel)
        r.write_tested(tested=[])
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_unticked_checklist(self):
        r = Release(self.rel)
        t = json.load(open(os.path.join(r.dir, "tested.json")))
        t["tested"][0]["checklist"]["wifi_join"] = False
        json.dump(t, open(os.path.join(r.dir, "tested.json"), "w"))
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_placeholder_marker(self):
        r = Release(self.rel)
        t = json.load(open(os.path.join(r.dir, "tested.json")))
        t["tested"][0]["tester"] = "PLACEHOLDER: maintainer name"
        json.dump(t, open(os.path.join(r.dir, "tested.json"), "w"))
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_tested_hash_of_other_image(self):
        r = Release(self.rel)
        t = json.load(open(os.path.join(r.dir, "tested.json")))
        t["tested"][0]["app_sha256"] = "0" * 64
        json.dump(t, open(os.path.join(r.dir, "tested.json"), "w"))
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_missing_part(self):
        r = Release(self.rel)
        os.remove(os.path.join(r.dir, r.parts[0]["file"]))
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_checksum_mismatch(self):
        r = Release(self.rel)
        with open(os.path.join(r.dir, r.parts[3]["file"]), "ab") as f:
            f.write(b"x")
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_wrong_offset(self):
        r = Release(self.rel)
        r.parts[0]["offset"] = 0
        r.write_parts()
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_hex_string_offset(self):
        r = Release(self.rel)
        r.parts[0]["offset"] = "0x2000"
        r.write_parts()
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_wrong_chip(self):
        r = Release(self.rel)
        r.write_parts(chipFamily="ESP32-S3")
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_unavailable_board(self):
        r = Release(self.rel)
        r.write_parts(board="waveshare-esp32-s3-touch-lcd-5", chipFamily="ESP32-S3")
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_path_traversal(self):
        r = Release(self.rel)
        r.parts[0]["file"] = "../evil.bin"
        r.write_parts()
        self.assertEqual(self.run_gen(), 1)

    def test_refuses_oversize_app(self):
        r = Release(self.rel)
        cfg = json.load(open(self.boards))
        for b in cfg["boards"]:
            if b["id"] == BOARD:
                b["app_max_size"] = 100
        self.boards = os.path.join(self.tmp, "boards.json")
        json.dump(cfg, open(self.boards, "w"))
        self.assertEqual(self.run_gen(), 1)

    def test_leak_scan(self):
        r = Release(self.rel)
        fn = os.path.join(r.dir, r.parts[3]["file"])
        data = open(fn, "rb").read() + b"\0http://nas.example-lab.lan\0"
        open(fn, "wb").write(data)
        r.parts[3]["size"], r.parts[3]["sha256"] = len(data), sha(data)
        r.blobs["app"] = data
        r.write_parts()
        r.write_tested()
        self.assertEqual(self.run_gen(), 1)
        self.assertEqual(self.run_gen("--no-leak-scan"), 0)

    def test_leak_scan_allows_portal_address(self):
        r = Release(self.rel)
        fn = os.path.join(r.dir, r.parts[3]["file"])
        data = open(fn, "rb").read() + b"\0192.168.4.1\0"
        open(fn, "wb").write(data)
        r.parts[3]["size"], r.parts[3]["sha256"] = len(data), sha(data)
        r.blobs["app"] = data
        r.write_parts()
        r.write_tested()
        self.assertEqual(self.run_gen(), 0)

    def test_one_bad_version_blocks_everything(self):
        Release(self.rel, "2.0.0")
        Release(self.rel, "2.1.0", tested=False)
        self.assertEqual(self.run_gen(), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_version_ordering_and_latest(self):
        for v in ("2.0.0", "2.0.0-p4.10", "2.0.0-p4.9", "1.9.0"):
            Release(self.rel, v)
        self.assertEqual(self.run_gen(), 0)
        idx = json.load(open(os.path.join(self.out, "index.json")))
        p4 = next(x for x in idx["boards"] if x["id"] == BOARD)
        self.assertEqual([v["version"] for v in p4["versions"]], ["2.0.0", "2.0.0-p4.10", "2.0.0-p4.9", "1.9.0"])
        self.assertEqual(p4["latest"], "2.0.0")

    def test_failed_run_keeps_previous_output(self):
        Release(self.rel, "2.0.0")
        self.assertEqual(self.run_gen(), 0)
        Release(self.rel, "2.1.0", tested=False)
        self.assertEqual(self.run_gen(), 1)
        idx = json.load(open(os.path.join(self.out, "index.json")))
        self.assertEqual(next(x for x in idx["boards"] if x["id"] == BOARD)["latest"], "2.0.0")

    def test_bad_directory_name(self):
        os.makedirs(os.path.join(self.rel, "latest"))
        self.assertEqual(self.run_gen(), 1)


if __name__ == "__main__":
    unittest.main()
