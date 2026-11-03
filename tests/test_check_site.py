import json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_site, gen_site  # noqa: E402
from test_gen_site import Release, ROOT, BOARD  # noqa: E402


class CheckSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        rel = os.path.join(self.tmp, "rel"); os.makedirs(rel)
        Release(rel)
        self.out = os.path.join(self.tmp, "site")
        gen_site.main(["--releases", rel, "--boards", os.path.join(ROOT, "boards.json"), "--out", self.out])
        lic = os.path.join(self.out, "licenses", BOARD, "2.0.0"); os.makedirs(lic)
        open(os.path.join(lic, "index.html"), "w").write("<html></html>")
        self.m = os.path.join(self.out, "fw", BOARD, "2.0.0")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_check(self):
        return check_site.main(["x", self.out])

    def test_ok(self):
        self.assertEqual(self.run_check(), 0)

    def test_hex_offset_rejected(self):
        p = os.path.join(self.m, "manifest-new.json"); d = json.load(open(p))
        d["builds"][0]["parts"][0]["offset"] = "0x2000"; json.dump(d, open(p, "w"))
        self.assertEqual(self.run_check(), 1)

    def test_update_touching_nvs_rejected(self):
        p = os.path.join(self.m, "manifest-update.json"); d = json.load(open(p))
        d["builds"][0]["parts"].append({"path": d["builds"][0]["parts"][0]["path"], "offset": 36864}); json.dump(d, open(p, "w"))
        self.assertEqual(self.run_check(), 1)

    def test_tampered_part_rejected(self):
        d = json.load(open(os.path.join(self.m, "manifest-new.json")))
        open(os.path.join(self.m, d["builds"][0]["parts"][3]["path"]), "ab").write(b"x")
        self.assertEqual(self.run_check(), 1)

    def test_external_script_rejected(self):
        open(os.path.join(self.out, "index.html"), "w").write('<script src="https://cdn.example/x.js"></script>')
        self.assertEqual(self.run_check(), 1)

    def test_missing_licence_page_rejected(self):
        os.remove(os.path.join(self.out, "licenses", BOARD, "2.0.0", "index.html"))
        self.assertEqual(self.run_check(), 1)

    def leak(self, rel, text):
        p = os.path.join(self.out, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(text)

    def test_private_denylist_from_outside_the_repo(self):
        # The maintainer's own words (login name, home domain) live in a file outside the repository, named by
        # $TWIDDLE_PRIVATE_DENYLIST; the public code names none of them.
        import io, contextlib
        dl = os.path.join(self.out, "..", "denylist-test.txt")
        open(dl, "w").write("# comment\nexample-secret-word\n")
        self.leak("licenses/%s/2.0.0/components.json" % BOARD, '{"sources": ["an example-secret-word here"]}')
        old = os.environ.get("TWIDDLE_PRIVATE_DENYLIST")
        try:
            os.environ["TWIDDLE_PRIVATE_DENYLIST"] = dl
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.run_check(), 1)
            self.assertIn("private denylist entry", err.getvalue())
            self.assertNotIn("example-secret-word", err.getvalue())  # names file and pattern label only
        finally:
            if old is None:
                os.environ.pop("TWIDDLE_PRIVATE_DENYLIST", None)
            else:
                os.environ["TWIDDLE_PRIVATE_DENYLIST"] = old
            os.remove(dl)

    def test_leak_paths_rejected_without_printing_value(self):
        import io, contextlib
        for text in ("/home/someone/code/x", "/Users/bob/x", "/tmp/claude-1000/x", "/root/x", "host.lan", "10.1.2.3", "192.168.1.20",
                     "me@mail.org"):
            self.leak("licenses/%s/2.0.0/components.json" % BOARD, '{"sources": ["%s"]}' % text)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.run_check(), 1, text)
            self.assertIn("components.json: leak scan", err.getvalue())
            self.assertNotIn(text, err.getvalue())

    def test_leak_in_new_file_types_rejected(self):
        self.leak("extra/notes.md", "see /home/x/y")
        self.assertEqual(self.run_check(), 1)

    def test_clean_extras_ok(self):
        self.leak("licenses/%s/2.0.0/components.json" % BOARD, '{"sources": ["<project>/main/a.c", "<home>/x"]}')
        self.leak("extra/portal.txt", "open http://192.168.4.1/ or noreply@github.com")
        self.assertEqual(self.run_check(), 0)

    def test_upstream_email_ok_only_in_licence_text(self):
        self.leak("licenses/%s/2.0.0/licenses.txt" % BOARD, "Copyright joel@rtems.org")
        self.assertEqual(self.run_check(), 0)
        self.leak("licenses/%s/2.0.0/components.json" % BOARD, "joel@rtems.org")
        self.assertEqual(self.run_check(), 1)

    def test_vendor_dir_skipped(self):
        self.leak("vendor/bundle.js", "/home/x/y")
        self.assertEqual(self.run_check(), 0)


if __name__ == "__main__":
    unittest.main()
