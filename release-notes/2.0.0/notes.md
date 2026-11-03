**Unofficial project, provided as is, with no warranty or guarantee of any kind.** Not made, endorsed or supported by Autoblow, Lovense, Kiiroo, Research & Desire, or any product or company named Twiddle, and not affiliated with them. Flashing can fail, brick a board or void its warranty. For adults only. Not a medical device. Keep a way to stop the device that you can reach by hand.

## Twiddle 2.0.0 - first public release

Same version for both boards. The images were tested on one unit of each board (see the test record on this page); other units, batches and chip revisions may behave differently.

### What is in
- **Autopilot**: timed sessions with a graph window (the last 10 s and the next 30 s, tap to jump, Draw to edit the whole session).
- **Scripts**: play motion scripts.
- **Themes**: Midnight (default) and Daylight.
- **Bluetooth toys**: connect, remember and forget devices on the Devices tab (Connect and Forget on a remembered device that is not connected).
- **Heart-rate edging** (work in progress, not yet tested with real sessions): Autopilot can follow a Bluetooth heart rate monitor. It has only been checked with computer tests. Do not rely on it. It is not a medical function.
- **Setup portal** at `http://192.168.4.1/setup` after joining the `Twiddle-Setup` Wi-Fi: Wi-Fi, token and Display. The form never shows stored passwords or tokens.
- **On-screen Wi-Fi setup**: a new or unconnected panel shows a Connect to Wi-Fi screen (Scan, network, password, Save & restart); the phone page `/setup` remains as the fallback. The Settings tab keeps a Save & restart bar in view while there are unsaved changes.
- **Per-device web password** (6 characters, no look-alikes), shown only on the panel's Settings tab. Admin pages answer 401 without a login; 5 wrong passwords in a row lock the login for 60 seconds.
- **Display select with trial and Keep**: a new Display choice is tried for 3 starts and goes back by itself unless you tap Keep.
- The web flasher itself and a release build with no Wi-Fi details inside.

### Per board
- **Guition JC1060P470C (ESP32-P4, 7 inch)**: the Display setting selects the panel table. Checked on two `_I_W_Y` units. The ESP32-C6 radio firmware is not part of this install.
- **Guition JC8048W550C (ESP32-S3, 5 inch)**: the Display setting is the pixel clock (default 16 MHz). An optional rotary encoder (work in progress, not tested on hardware) is detected at start-up if present. The firmware links the LGPL-2.1 Arduino-ESP32 libraries; the licence page lists the source and rebuild files.

### Known limitations
- ESP32-S3: the on-screen keyboard and scrolling in the Settings list are slow (about 0.3 s per redraw; measured, cause not yet found). First-time Wi-Fi setup works but needs patience; the phone setup page is the alternative.
- ESP32-P4: the V2 panel table is verified only on two `_I_W_Y` units, not on a unit labelled V2. Chip revision 3.0 is not supported; only revision v1.3 was tested.
- The rotary encoder is not implemented on the P4.
- Heart-rate edging and the S3 encoder are untested with real hardware or sessions.
- ESP32-S3: the CH340 USB chip may need a driver on Windows; if the installer cannot connect, hold BOOT, tap RESET, release BOOT.
- Only the models shown on this page are covered. The Waveshare ESP32-S3 board is not part of this release.
- Tested on one unit of each board (see the test record on the page): install, Wi-Fi setup on the panel's screen, the display trial and revert, update keeping settings, the login lockout. Not exercised in the final pass on these exact images: toy control on the Devices tab and the Autopilot graph window (checked on earlier builds only).
- No warranty and no promise of support or updates.
