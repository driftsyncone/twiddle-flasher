# twiddle-flasher

> **Unofficial project, provided as is, with no warranty or guarantee of any kind.** Not made, endorsed or supported by Autoblow, Lovense, Kiiroo, Research & Desire, or any product or company named Twiddle, and not affiliated with them. Names are used only to describe compatibility. See [Disclaimer and safety](#disclaimer-and-safety).

Static web flasher for the Twiddle firmware (ESP32 display boards). Plain HTML/CSS/JS plus a vendored, unmodified
[esp-web-tools](site/vendor/esp-web-tools/VENDOR.md) build; no CDN and no third-party request at runtime.
Site code and scripts: Apache-2.0 (`LICENSE`). Design: see the Twiddle web-flasher design v2 notes.

### Licences

The site code and scripts here are Apache-2.0 (`LICENSE`). The flasher button is [esp-web-tools](site/vendor/esp-web-tools/VENDOR.md)
(Apache-2.0) with its dependencies, unmodified; their licence texts are in `site/vendor/esp-web-tools/`. The firmware images this site
installs are a different work: Twiddle's own code is CC BY-NC-SA 4.0 (unchanged), and the third-party software inside each image keeps its
own licence. For every published version and board the site carries a generated notices page (`licenses/<board>/<version>/`, made by
`scripts/gen_notices.py --check` from the linker map, with the full licence texts). The ESP32-P4 images contain no GPL or LGPL component.
The ESP32-S3 image statically links LGPL-2.1+ Arduino-ESP32 components, for which the firmware repositories carry an additional-permission
paragraph (`LICENSE-NOTES.md`, DRAFT, not read by a lawyer) and a written offer with each release. This is documentation, not legal advice.

### Disclaimer and safety

- No warranty or guarantee of any kind; use at your own risk. Flashing can fail, brick a board or void the maker's warranty.
- For adults only, and only with the consent of everyone involved.
- Not a medical device. Any heart-rate or edging feature is not a monitoring or medical function; do not rely on it for health.
- Software and wireless links can fail. Always keep a way to stop the device that you can reach by hand.
- Vendor and product names are used only to describe compatibility; no affiliation.

## Feature requests and bug reports

Use [GitHub Issues](https://github.com/driftsyncone/twiddle/issues), one issue per request or bug. Say which board and firmware version you have, what you expected and what happened, and attach logs only after removing tokens and Wi-Fi passwords. Requests are welcome, but there is no promise of a reply, a timeline or support, in line with the unofficial, no-warranty notice at the top. Do not put secrets in a report, security-related ones included.

## Layout
- `site/` the static site (picker `index.html`, `app.js`, `style.css`, `licenses/`, `vendor/esp-web-tools/`).
- `boards.json` board catalogue: identification text, chip family, serial type, **expected part offsets (decimal)**, app slot size, which parts an update writes, leak-scan patterns.
- `scripts/gen_site.py` release parts + `tested.json` -> `fw/<board>/<ver>/{parts, manifest-new.json, manifest-update.json, SHA256SUMS}`, `latest.json`, `index.json`.
- `scripts/gen_notices.py` third-party notices page + copyleft link check from a P4 build (map file, compile_commands, dependencies.lock). Exceptions with reasons: `scripts/notices-allow.json`.
- `scripts/gen_notices_pio.py` the same for the ESP32-S3 (PlatformIO / Arduino-ESP32) build: reads the linker map (only objects with bytes in the image count) and `compile_commands.json` (`pio run -e panel-release -t compiledb`), lists the statically linked LGPL groups, the prebuilt Espressif radio blobs and the toolchain runtime, scans linked sources for GPL/LGPL headers, and fails on an LGPL group, GPL source or prebuilt archive that has no reviewed entry in `scripts/notices-allow-s3.json`. The page carries the full LGPL-2.1 text and lists the LGPL release assets.
- `scripts/check_site.py` pre-deploy checks (hashes, esp-web-tools manifest format, update never touches NVS/bootloader/table, no external requests, licence page per version).
- `scripts/assemble.sh` builds `dist/`; `scripts/relocate.sh` rewrites the base URL for another host; `scripts/vendor-esp-web-tools.sh` rebuilds the vendored bundle from the pinned commit.
- `.github/workflows/pages.yml` drafted, never run: assembles from release assets of `driftsyncone/twiddle`, deploys via Actions.
- `scripts/assemble.sh` generates `site/licenses/<board>/<version>/` itself from a `notices.json` in the release folder (`{"<board-id>": {"project": FW_REPO, "build": FW_BUILD_DIR}}`), or copies a ready `licenses-<board-id>/` folder; it stops when `gen_notices.py --check` fails. The check also fails if a prebuilt radio library is linked; `scripts/notices-allow.json` holds the reviewed exceptions and the `blobs` statements.
- Tests: `python3 -m unittest discover -s tests`.

## Release process
The full publishing runbook (who does what, GitHub steps, rollback) is in [PUBLISHING.md](PUBLISHING.md).

1. In the firmware repo (P4: branch `flasher-dist` adds this; S3: branch `release-prep-s3`), bump `FW_VERSION` to a real version (no `-dev`/`-pN` for a public release), build, run `tools/dist.sh`. It writes the app, bootloader, partition-table and otadata parts (S3: boot_app0 at 0xe000) and `twiddle-p4-<ver>.parts.json` (S3: `twiddle-s3-<ver>.parts.json`). The S3 build is `pio run -e panel-release`, which has no secrets in it.
2. Flash that exact image on real hardware and work through the checklist (boots, setup portal, Wi-Fi join, OTA from previous release). Write `tested.json` (see `examples/tested.example.json`). It must carry the **sha256 of the app image you tested**.
3. Write `notes.md` (the changelog shown on the page; mirrors CHANGELOG.md).
4. Generate the notices from the same build: `scripts/gen_notices.py --project <fw repo> --build <fw repo>/build --version <ver> --out releases/<ver>/licenses-<board-id> --check`. Resolve every FAIL and every NEEDS REVIEW warning. For the S3: `scripts/gen_notices_pio.py --project <fw repo> --build <fw repo>/.pio/build/panel-release --version <ver> --assets <lgpl-assets.json> --out releases/<ver>/licenses-guition-jc8048w550c --check` (run `pio run -e panel-release -t compiledb` first), or put `"guition-jc8048w550c": {"tool": "pio", "project": ..., "build": ..., "compdb": ..., "assets": ...}` in `notices.json`. Also run the firmware repo's `tools/lgpl-package.sh <tag>` and publish the files it writes next to the images (see `docs/lgpl-compliance.md` there).
5. Put everything in `releases/<ver>/` (or attach as release assets, see the workflow header) and run `scripts/assemble.sh releases dist`. Serve `dist/` over HTTPS (localhost also works) to try it.

## The "tested images only" gate
`gen_site.py` refuses (non-zero exit, nothing written, so nothing deployable) when: the version folder has no `tested.json`; the board is not listed in it; a checklist item is not ticked; `app_sha256` differs from the app being published; the board is marked `unavailable` in `boards.json` (Waveshare); a part file is missing, empty, oversized, overlapping, has a hex/wrong offset or a checksum differing from the parts manifest; the binary contains home-network strings (leak scan; `192.168.4.1` allowed). `assemble.sh` additionally refuses a version without a licence page.

## Local verification done (2026-11-02)
Unit tests (35), assembling a demo site from the existing build of the main P4 checkout with a DEMO `tested.json`, serving it with `python3 -m http.server`, headless Chromium: cards, version/mode switching, manifest URL changes, esp-web-tools dialog opens, zero third-party requests, no console errors, no horizontal scroll on a 380 px viewport.

## Found on hardware (2026-11-02)
First real P4 flash from Chrome (esp-web-tools b027c3c, esptool-js 0.7.0, rev 1.3 over native USB, "Update" manifest): the flash worked at the transport level but **erased the whole chip** (bootloader, table, NVS, ota_1 gone; the board then looped `invalid header: 0xffffffff`). Cause: esp-web-tools erases silently unless the manifest has `new_install_prompt_erase: true` (it is `prompt ? ask : erase`). Both manifests now set it, `check_site.py` enforces it, and the Update page says to leave "Erase device" unticked. NOT yet re-tested on the board. Restored from a full flash backup. Also: reading flash over this USB connection fails on some large blocks (esptool `read_flash` at 0x185000 "Packet content transfer stopped"); 1 KB reads work.

## NOT done (needs hardware or a decision)
- **No flash was ever attempted.** P4 browser flash on chip rev 1.3 over native USB (auto reset, BOOT+RESET path, interrupted flash, re-enumeration, `serialType: "cdc"` matching, erase and update manifests) is the go/no-go test; if esp-web-tools fails, fall back to esptool-js directly.
- The firmware prerequisites: Display select in the setup portal, per-device password flow, secrets-free build, the p4.10 panel-variant merge. Done in firmware 2.0.0-p4.13 (branch `release-prep`): the password is shown only on the panel's Settings tab; the page text says so. Still to be checked on a board.
- Update manifest assumes the partition layout is unchanged between versions; it rewrites otadata so the new app in ota_0 boots. Untested on a board that currently runs from ota_1.
- S3 (branch `s3-support`, firmware branch `release-prep-s3`): the card, the parts layout (bootloader 0, partition table 32768, boot_app0 57344, app 65536), an update that writes only boot_app0 + app, `tools/dist.sh`, the LGPL notices generator and the source/relink package script exist and are checked offline. NOT done: no S3 image was ever flashed from the browser (CH340 reset into download mode, BOOT+RESET positions, flash time, Windows driver behaviour are UNVERIFIED), no tested image, no photo. The Guition S3 card says "no tested image published yet" until a `tested.json` exists; Waveshare stays unavailable.
- `check_site.py` used one NVS range (0x9000-0xF000) for every board; the S3's `boot_app0` is at 0xE000, inside that range, so an S3 update manifest would have been rejected. Each board now carries `nvs_region` in `boards.json` (P4 0x9000-0xF000, S3 0x9000-0xE000), `gen_site.py` refuses a board whose update parts touch it, and `check_site.py` uses it.
- Photos are SVG placeholders; the BOOT/RESET positions must be checked on the real board.
- `gen_notices.py` on the P4 release build (2.0.0-p4.13): passes with no warnings. newlib reviewed (GNU entries in COPYING.NEWLIB are linux-target-only; per-member source headers NOT individually checked). The P4 image links no prebuilt radio blob (no esp_phy, esp_wifi/lib, bt/controller archive; the check now fails if one appears). Licence files of those blobs were read for the S3 case (plain Apache-2.0 text, hashes in `scripts/notices-allow.json`), whether that text is meant to cover the binaries is NOT verified. C6 firmware is not in the published parts. Not legal advice.
- GitHub repo, Pages, DriftSyncOne publishing identity, trademark search, workflow action pinning: not done.

## Dry run without hardware (2026-11-02)
Release candidate 2.0.0-p4.13 from `release-prep`: `tools/dist.sh` parts + a `tested.json` with PLACEHOLDER markers and unticked boxes -> `gen_site.py` REFUSED (expected). A clearly fake `tested.json` (scratch folder, not in this repo) + `notices.json` -> `assemble.sh` produced a site that `check_site.py` accepts. The maintainer must fill: `chip_rev`, `date` (YYYY-MM-DD), `tester`, `app_sha256` (sha256 of the tested `twiddle-p4-<ver>.bin`; must equal the published image), `variants_tested`, and tick `boots`, `setup_portal`, `wifi_join`, `ota_from_previous` (true, or "n/a" for the last only); any value containing PLACEHOLDER is refused. Also write `notes.md` and `notices.json`.

## Notes for the Guition ESP32-S3 install

- The board talks through a CH340 USB-serial chip (`serialType: "uart"`). Windows may need the WCH CH340 driver (which versions install it themselves: UNVERIFIED). The BOOT and RESET positions and whether the browser's automatic reset works are UNVERIFIED on a real board; the card says so.
- After the install the setup form is at `http://192.168.4.1/setup` (join `Twiddle-Setup`, password `twiddle-setup`). The stored Wi-Fi password and token are never shown in the form; an empty field keeps them. The "Display pixel clock" choice starts a trial: tap Keep on the panel, or after three unconfirmed restarts it goes back.
- The web password is on the panel's Settings tab only ("Web login").
- The image statically links LGPL-2.1 Arduino-ESP32; the licence page for each S3 version says so and lists the source and rebuild assets.

## Notes for the ESP32-P4 install

- After the install the setup form is at `http://192.168.4.1/setup` (join `Twiddle-Setup` first). A phone browser may refill old Wi-Fi or token values, so check the fields before saving.
- The default Display (V2 table) drove both `JC1060P470C_I_W_Y` units we tried; "new panel" is an untested alternative if the screen stays black. Other batches may differ.
- The P4's C6 radio firmware is not part of this install; factory C6 firmware can be too old to join Wi-Fi (see `docs/c6-firmware.md` in the firmware repository).
- Twiddle is a free, non-commercial open-source project, not affiliated with other products or companies named Twiddle.
