# Vendored esp-web-tools

- Upstream: https://github.com/esphome/esp-web-tools (Apache-2.0, see `LICENSE`)
- Pinned commit: `b027c3c939dd660e1f7abb7efd6404839453e759` (main, 2026-11-02, "Adopt gh-actions-lock for GitHub Actions (#748)"). Chosen because `main` depends on esptool-js ^0.7.0 (P4 fixes); release 10.4.0 bundles 0.6.x.
- Not modified. Built with `npm ci && script/build` (tsc + rollup, output `dist/web/`), by `scripts/vendor-esp-web-tools.sh` in a throwaway directory.
- Bundled runtime deps (versions from package-lock at the pin): esptool-js 0.7.0 (Apache-2.0), improv-wifi-serial-sdk 2.8.1 (Apache-2.0), lit 3.3.3 / lit-html 3.3.0 / lit-element 4.2.0 / @lit/reactive-element 2.1.0 / @lit/context 1.1.6 (BSD-3-Clause), @material/web 2.5.0 (Apache-2.0), tslib 2.8.1 (0BSD), pako 2.2.0 (MIT AND Zlib), atob-lite 2.0.0 (MIT). Licence files are in `licenses/` (lit-html, lit-element, reactive-element and context are covered by the same Google BSD-3 text as `lit.LICENSE`). Upstream's repository has no NOTICE file at this commit; esptool-js's LICENSE is the unfilled Apache template, copyright (c) Espressif per its README.
- Network audit (static): the bundle contains no runtime fetch/import of third-party hosts. URLs present are help links shown to the user (wch.cn, silabs.com USB driver pages, my.home-assistant.io, esphome.github.io) and the SVG namespace. Still confirm in the browser network panel before publishing (UNVERIFIED in a real browser).
- Entry point: `install-button.js` (defines the `<esp-web-install-button>` element); the other files are lazy chunks it imports relatively.

## SHA-256
    b3982c8963092ee9a24f07d4e65eb60b4dbfc79913f2601decf43d3d7466cbea  esp32-BlyKoTgy.js
    a1f24fc2ce757cf81715deb57d9eece4740934816f7253edd812e37cf954db75  esp32c2-Bmu-jpVE.js
    6fab8199779972b2f5bbc22ca6f1febb92f16513fd96fea1467b49a90f2b22b3  esp32c3-81Rr-aQE.js
    a9881ea78d3742b703aedfdce62f5c63f391fb72c3e8c492f3a0ef93253b38eb  esp32c5-Bq6mXcb5.js
    efe3cdb1b1814af740af06c9809cb53fd48ca19fc91af04d754695fc97efe08c  esp32c61-DmDn041x.js
    9a47e98dc3e0e1e9a21190d6a7ffbc320b1ce86d2aaa712ed6aa2d68c5561a94  esp32c6-yQoBKrxY.js
    3099acc7ba032419d89b00c06c18355b5043dd6ced5bc66abb2135698d01e6bd  esp32h2-B8bZhHv5.js
    9b3aff6c4192bc7a435699df140221eb6336ec88a647e63a0a9f2fcb6685c049  esp32h4-KyNsS-mo.js
    19c05d88a44666c9c26dfacd1211ff402a50e4a03a18c4cfcb9354f8ee23cef0  esp32p4-o74i42i3.js
    056013ab34b89e4b8aa2fa7f74c0eff79e685360897e802784cd0f22a47fd975  esp32p4-rev1-DEdUM_9Q.js
    976707629707461d0ba23a6237b2413194a290cc7eb6cccc91e9cdcecaab06c1  esp32s2-O1Tyu6IT.js
    62b0fc81c7d4faa86c7b2da883db0b6acdf7062398441b2ce07d9cd2a9b0f8f4  esp32s31-Ef8NLP2_.js
    298f31b5a77a9bdf42fc09ce95a9b67a846479a6129015ad5b2e39a92bcdd1b8  esp32s3-WXxMoV8x.js
    34154df294eeb7701958a7244298813bc19cb979713e31a2bd004a43b002cce7  esp8266-DsDItw_h.js
    fa135d3b755573170d75a36e8250b1c6a6e95fcb7c9c5679d9061232b8d63e05  index-CAwQL4m1.js
    06f4944a6c27c4e3324c2000ea3cd5d393f628b6786ddc73c82bfe8d01429ac0  install-button.js
    e787722eebe1279590f69f408b2e31803dbceee1446999f1474dd4834a398288  install-dialog--NPc6QLx.js
    07726c7af52ea64ae1a58472f6500509d2b6bac8456daa04e4ec8edd6c7ed814  styles-BiOOVrm2.js
