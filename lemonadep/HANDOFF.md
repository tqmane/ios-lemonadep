# lemonadep (OnePlus 9 Pro) -- handoff, read first (2026-10-31)

iOS 16.5 (HackiOS: furangelz's hackios-xnu-kernel + hackios-xnu-userland, branch `lemonadep`) runs on the
OnePlus 9 Pro **standalone**: power on, iOS starts, no computer. The full history of how each piece was
found is in [HANDOFF-log.md](HANDOFF-log.md); this page is the state and the recipes.

## What works / what does not

| Works | Notes |
|---|---|
| Boot without a PC | boot_b = UEFI + xnuloader + kernel + root.apfs; the 2.4 GB system image read from userdata at 16 GiB (`diskrd`) |
| GPU (Adreno 660, Mesa GL), touch, battery, backlight | furangelz's drivers + lemonadep patches. `metal=2` is the working split (apps get Metal, backboardd keeps OpenGL ES); the image must be built with `GL=1` (root.apfs ~25 MB, not ~18.6 MB). Panel at 120 Hz with the vsync-period fix + `fb_hz=120` |
| /private/var kept between boots | var_store in userdata from 20 GiB; saved every 30 min, on iOS power off, on a five-finger hold (which powers off) |
| Wi-Fi (QCA6490 / ath11k over PCIe) | joins `fw-wlan/network` at boot; configd's own Wi-Fi service and DHCP; status bar/Settings show it; join from Settings works |
| Safari (pages, video) | needs apsd left out (see below) |
| Location (Wi-Fi positioning) | locationd added + Location Services forced on |
| Bigger-phone layout (414x896 pt) | boot-args `fbwidth=1242 fbheight=2688` (iPhone XS Max size at 3x; MiniIOMobileFramebuffer scales to the 1080x2412 panel). User: "looks better". Old 375x812 image kept as out/hackios/lemonadep-standalone-375pt.img |
| Dynamic Island: NOT working | `fbwidth=1290 fbheight=2796` (14 Pro Max size, 430x932 pt) moves the status bar into the island layout, but no pill and no Live Activities (timer) appear: the island needs more than the screen size (likely MobileGestalt's ArtworkDeviceSubType 2796 / island capability, plus SystemAperture rendering). Image kept as lemonadep-standalone-430pt.img. Further tests (loader overriding the device subtype, as DynamicCow does) showed the island as a black square with home-button behaviour; reverted, not in the code. |

| Not working | Cause (as far as known) |
|---|---|
| Sound (speaker, Safari, system sounds) | user, 2026-10-31: nothing heard although adsp=1 starts the audio DSP; speaker amplifier/route on this phone not brought up -- next candidate (furangelz's redwood audio is for another codec/amp) |
| Weather numbers | WeatherKit requests are Mescal/FairPlay-signed (`code=12`, "Failed to fetch hardware info"), and an unsigned request answers 401. WeatherCore's internal "Local - Mock Server" environment (`http://localhost:5033`, keys `weather.environment.contentEnvironment/localServerURL/localServerPort`) is now reachable from an injected library, but as of 2026-11-03 the app sends no request at all — see hackios/FINDINGS-2026-11-01-03.md §4 |
| Maps tiles | **not** Metal and not the renderer: Maps draws its own UI and `gspe19-ssl.ls.apple.com` answers **403, 0 bytes** to unsigned tile requests (control `bag.xml` 200 in the same session). Needs a different tile source behind GeoServices |
| Bluetooth, cellular, camera | not started |
| Power button shutdown | does not save /var; use the five-finger hold or iOS's power off |
| Location toggle in Settings | not shown (MobileGestalt: no GPS?); the switch is forced on instead |
| First Wi-Fi association after radio start | lost EAPOL; worked around with a retry (root cause open) |
| End-of-run panic on the way back to the loader | "Console I/O from interrupt-disabled context" in dev runs only |

Research 2026-10-31 (before spending device time): **sound** -- postmarketOS lists audio playback, mic and
headset as *broken* on lemonadep even under Linux (wiki.postmarketos.org, OnePlus 9 & 9 Pro page), so there is
no known-good speaker path to port. **Metal for apps** (likely behind Maps tiles) -- the working prior art is
UniXNU's NativeMetal (Metal -> metal2vulkan -> Mesa Turnip, as superboyyy/hakios-arm64e-dada uses on the
Adreno 830); furangelz's own AIR->Adreno route is in progress (userland docs/air.md). Both are GPU-stack
projects, coordinate with the GPU collaborator rather than start one here.

## The fixes that matter (and where)

- **Safari froze after every page**: its History service hangs at start in `[APSConnection setDelegate:]`, a
  synchronous call to apsd that never answers. `DENY_EXTRA=com.apple.apsd` (lemonadep.conf USERLAND_VARS).
- **Apps "offline" / Settings could not join**: en0 must exist before configd starts (`wifi_mac`, made at
  kernel start: lemonadep_wlan.c); wifid needs requests 422/419/29 answered, SIOCSIFLLADDR accepted
  (Private Wi-Fi Address; the radio follows en0's address), and TKIP/WPA1 capability bits for WPA/WPA2-mixed
  networks (redwood_apple80211.c, redwood_net.c, lx_80211.c).
- **Wi-Fi in the full boot**: 64 MB of DMA pool reserved before the GPU (`redwood_lx_reserve`).
- **Location**: locationd kept by select-system.py, `ALLOW=locationd`, `LOCATION_ON=1`
  (`LocationServicesEnabledIn8.0`), init.c re-applies 'F' skeleton files after the /var restore.

Patches: `hackios/patches/` -- kernel-0001..0004, lx-0001, userland-0001 (apply in `~/fkernel` with `git apply`;
userland-0001 also touches `ios165/select-system.py`). Kernel driver: `hackios/kernel/lemonadep_wlan.c`.

## Build and install (WSL lab at ~/fkernel)

1. furangelz's trees at `~/fkernel` (branch lemonadep), patches applied, Mu-Silicium lemonadep FD built,
   iOS 16.5 IPSW extracted by `ios165/fetch.sh`. Wi-Fi: `~/fkernel/fw-wlan/` (firmware pulled from the
   phone, `network` = name and passphrase; all gitignored).
2. `common/build.sh lemonadep` (kernel, loader, images), then `bash hackios/build-standalone.sh`.
3. Phone in TWRP: `hackios/install-standalone.ps1 -SystemImage`; phone in fastboot: `-Boot`.
   Back up boot_<slot> first; undo with `fastboot flash boot_b backup/partitions/boot_b.img`.

Dev runs (logs over USB): `fastboot boot out/hackios/lemonadep-boot.img`, then `hackios/run-live.ps1`
(`-Resident` reuses the system image the loader holds). Fastboot needs the buttons (Power + Volume Down).

## Where the last two days are written down

`hackios/FINDINGS-2026-11-01-03.md` is the consolidated record of 2026-11-01..03: the metal/GL split and why
`metal=3` fails, the 120 Hz measurements (3220 vs 3060 frames — no measured gain, the counters measure app
redraw), Weather's Mescal chain and its local-server key discovery, the Maps 403, the MP2650 charger, the
kernel link-time break and the hands-free USB test loop. Read it before repeating any experiment.

## Debugging tools that paid off

- `OSLOG='com.apple.wifid ... debug'` (image build) and `applog=1 applog_name=Safari,...` (boot-arg):
  daemons' and apps' os_log on the console.
- `stack_test -k NAME` (hackios/userland/stack_test.c): kernel stackshot of a hung process, decode with
  xnu's `tools/lldbmacros/kcdata.py`, symbolicate with `ipsw dyld a2s` (cache extracted WITH .symbols).
- `net_test` (hackios/userland/net_test.m): store, reach, fetch, `fetch3` (HTTP/3), big UDP/TCP, `asuser`.

## Phone state now

boot_b: standalone image of 2026-10-30 23:40 (Wi-Fi, Safari, location). userdata raw: 0..11.3 GB old
ios-sweet root, 16 GiB system image, 20..24 GiB /var store. Android is gone (recovery + bootloader intact).
