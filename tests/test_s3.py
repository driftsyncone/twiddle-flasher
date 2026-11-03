"""ESP32-S3 board (guition-jc8048w550c): release layout, update manifest safety, check_site NVS region."""
import hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_site, gen_site  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
BOARD = "guition-jc8048w550c"
LAYOUT = {"bootloader": 0, "partition-table": 32768, "boot_app0": 57344, "app": 65536}
VER = "2.0.0"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make_release(rel, tested=True):
    d = os.path.join(rel, VER)
    os.makedirs(d)
    parts, blobs = [], {}
    for n, off in LAYOUT.items():
        blobs[n] = (n.encode() + b"-s3-") * 40
        fn = f"twiddle-s3-{VER}.bin" if n == "app" else f"twiddle-s3-{VER}-{n}.bin"
        open(os.path.join(d, fn), "wb").write(blobs[n])
        parts.append({"name": n, "offset": off, "file": fn, "size": len(blobs[n]), "sha256": sha(blobs[n])})
    json.dump({"schema": 1, "board": BOARD, "version": VER, "chipFamily": "ESP32-S3",
               "flash": {"flash_mode": "dio", "flash_size": "16MB", "flash_freq": "80m"}, "parts": parts},
              open(os.path.join(d, f"twiddle-s3-{VER}.parts.json"), "w"))
    if tested:
        json.dump({"schema": 1, "version": VER, "tested": [{
            "board": BOARD, "chip_rev": "v0.2", "date": "2026-11-10", "tester": "maintainer", "app_sha256": sha(blobs["app"]),
            "checklist": {"boots": True, "setup_portal": True, "wifi_join": True, "ota_from_previous": "n/a"}}]},
            open(os.path.join(d, "tested.json"), "w"))
    return d


class S3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.rel = os.path.join(self.tmp, "rel"); os.makedirs(self.rel)
        self.out = os.path.join(self.tmp, "site")
        self.boards = os.path.join(ROOT, "boards.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def gen(self, boards=None):
        return gen_site.main(["--releases", self.rel, "--boards", boards or self.boards, "--out", self.out])

    def test_board_entry(self):
        b = next(x for x in json.load(open(self.boards))["boards"] if x["id"] == BOARD)
        self.assertEqual((b["chipFamily"], b["serialType"]), ("ESP32-S3", "uart"))
        self.assertEqual(b["parts_layout"], LAYOUT)
        self.assertEqual(b["update_parts"], ["boot_app0", "app"])  # never the bootloader, the table or NVS
        self.assertEqual(b["nvs_region"], [0x9000, 0xE000])        # default_16MB.csv: nvs 0x9000 size 0x5000, otadata 0xe000
        self.assertTrue(any("UNVERIFIED" in t for t in b["download_mode"]))  # BOOT/RESET positions are not verified

    def test_gate_without_tested_json(self):
        make_release(self.rel, tested=False)
        self.assertEqual(self.gen(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "index.json")))

    def test_manifests_and_check_site(self):
        make_release(self.rel)
        self.assertEqual(self.gen(), 0)
        base = os.path.join(self.out, "fw", BOARD, VER)
        new = json.load(open(os.path.join(base, "manifest-new.json")))["builds"][0]
        upd = json.load(open(os.path.join(base, "manifest-update.json")))["builds"][0]
        self.assertEqual((new["chipFamily"], new["serialType"]), ("ESP32-S3", "uart"))
        self.assertEqual([p["offset"] for p in new["parts"]], [0, 32768, 57344, 65536])
        self.assertEqual([p["offset"] for p in upd["parts"]], [57344, 65536])
        lic = os.path.join(self.out, "licenses", BOARD, VER); os.makedirs(lic)
        open(os.path.join(lic, "index.html"), "w").write("<html></html>")
        self.assertEqual(check_site.main(["x", self.out]), 0)  # 57344 (otadata) is NOT inside the S3's NVS region
        # an update manifest that writes NVS or the bootloader/table is rejected
        mp = os.path.join(base, "manifest-update.json"); m = json.load(open(mp))
        m["builds"][0]["parts"].append({"path": m["builds"][0]["parts"][0]["path"], "offset": 36864})
        json.dump(m, open(mp, "w"))
        self.assertEqual(check_site.main(["x", self.out]), 1)

    def test_board_that_updates_the_bootloader_is_refused(self):
        make_release(self.rel)
        cfg = json.load(open(self.boards))
        next(x for x in cfg["boards"] if x["id"] == BOARD)["update_parts"] = ["bootloader", "boot_app0", "app"]
        p = os.path.join(self.tmp, "boards.json"); json.dump(cfg, open(p, "w"))
        self.assertEqual(self.gen(p), 1)

    def test_board_without_nvs_region_is_refused(self):
        make_release(self.rel)
        cfg = json.load(open(self.boards))
        del next(x for x in cfg["boards"] if x["id"] == BOARD)["nvs_region"]
        p = os.path.join(self.tmp, "boards.json"); json.dump(cfg, open(p, "w"))
        self.assertEqual(self.gen(p), 1)

    def test_wrong_offsets_refused(self):
        d = make_release(self.rel)
        pj = os.path.join(d, f"twiddle-s3-{VER}.parts.json"); j = json.load(open(pj))
        for p in j["parts"]:
            if p["name"] == "boot_app0":
                p["offset"] = 61440  # the P4's otadata offset
        json.dump(j, open(pj, "w"))
        self.assertEqual(self.gen(), 1)

    def test_p4_image_refused_for_s3_board(self):
        d = make_release(self.rel)
        pj = os.path.join(d, f"twiddle-s3-{VER}.parts.json"); j = json.load(open(pj))
        j["chipFamily"] = "ESP32-P4"
        json.dump(j, open(pj, "w"))
        self.assertEqual(self.gen(), 1)


if __name__ == "__main__":
    unittest.main()
