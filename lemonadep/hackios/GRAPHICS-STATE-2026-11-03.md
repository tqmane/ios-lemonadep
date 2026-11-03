# Graphics state, 2026-11-03

## Fixed and seen on the phone by the user

"Back to the state before the Metal experiments": wallpaper, transparency, blur, smooth animation,
Wi-Fi joined (`en0 has IPv4 192.168.0.22` 3 s after the radio came up), battery UI.

Two independent causes, both now understood:

1. **The window server was being handed the Metal device.** `metal=3` in `lemonadep.conf` shows the
   device to every process including `backboardd` (`HakiosMetal.m`, `shownToThisProcess()`). The
   window server cannot run on Metal on this port: its own `metallib_url` load fails, and it then
   reports "Failed to initialize Metal or OpenGLES contexts" and falls back to the software renderer.
   `camtl=1` was also still in `BOOTARGS` although the current userland tree has no `camtl` code at
   all (dead flag).

   Now **`metal=2`** — every process but `backboardd` — which is the "sandwich": applications get a
   Metal device, the window server keeps the proven OpenGL ES path. Log proof:
   `redwood: metal: no device in this process; CoreAnimation keeps OpenGL ES by itself` and
   `accelerated renderer (0x...)`, with zero "Software renderer" lines.

2. **The image itself had no GL stack.** The build that was on the phone had been made without `GL=1`:
   `/redwood/lib` listed every other dylib but no `libredwood-gl.dylib`, and neither image had Mesa.
   CoreAnimation could not initialize a GL context either, so the screen ran on the software renderer
   ("redwood: no accelerated renderer; the software one will draw").

   Rebuilt with `SKIP="kernel loader boot" USERLAND_VARS="GL=1 ADSP=1 DENY_EXTRA=com.apple.apsd
   ALLOW=locationd LOCATION_ON=1" common/build.sh lemonadep`. `root.apfs` 18.6 -> 25.3 MB,
   payload 41.1 MB (loader limit 64 MiB).

Verified from the phone's own log (`out/hackios/frames1.log.raw`, `glframes=1`):
`display surface 3/4, 47 draws into it` — CoreAnimation is drawing the display's IOSurfaces, and
`3.5 ms` of CPU per frame (2134 calls, 2222 triangles), i.e. the renderer is not the bottleneck.

## Open: 120 Hz, tearing, stutter

The panel is at 120 Hz — the kernel says so itself: `synaptics: the display refreshes 120 times a
second (gpio82)`. The frame cadence measured from the log is ~17 ms (~58 fps), and two things explain it:

- `MiniIOMobileFramebuffer.cpp` defaults `kFBRefreshHz` to **60** (boot-arg `fb_hz`). The vsync timer
  and every deadline are derived from `refreshHz()`.
- `IOMobileFramebufferUserClient::vsync()` sends CA `now` in the slot CA reads as the **refresh
  period** (`a2 + a3` is the next deadline), so CA's next deadline comes out as roughly `now + now`.
  This is exactly what overlay 0101 (PixeliOS) fixes, and that overlay is not in this tree.

`tools/fix-vsync-period.py` applies the period fix; it is applied in **both** the overlay source
(`~fkernel/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp`) and the build tree. The boot-arg
`fb_hz=120` was added and then **reverted** in `lemonadep.conf`, because it is only half the fix and
its effect without the period is unmeasured.

**Blocker to landing it:** the kernel will not rebuild in this tree. `xnu-build.sh` now fails at
`config_all_bootstrap` with `exported name not in import list: IOService::…` from
`check_all_exports`, which needs `allsymbols` from `nm` of the kernel. This began after
`BUILD/obj` was deleted to force a clean build (`mach.development.bcm2837.unstripped` existed again
afterwards, and the Nov-2 kernel was preserved as `~/fkernel/mach.nov2.bak`, so the payload in
`out/hackios/` is still the known-good kernel). The reliable way out is a fresh tree:
`xnu/apply.sh` into a new directory, copy the patched file in, build there.

## Still broken, and why

- **Weather digits** — the renderer is innocent: the forecast never arrives. `AMSMescalFairPlay` init
  fails with `code 12 "Failed to fetch hardware info"`, so `WeatherDataService` cannot create its local
  signature and abandons the request before sending it (verbatim log in NEWER-IOS-AND-CHARGING.md §7).
  An unsigned fetch of the same URL from `net_test` answers **401**, so Apple is refusing a request the
  app also cannot sign. Not a graphics bug, and not fixable in the kernel: `fairplayd` never calls IOKit
  (three runs, zero `IOServiceMatching`/`IOServiceOpen`), it returns from `main` inside obfuscated code.
- **Maps tiles** — same class, measured: the tile host `gspe19-ssl.ls.apple.com` answers **403** to an
  unsigned request. Maps does get a Metal device now (`metal=2`); it simply has no tiles to draw.
- **Charging** — `adsp=1` wants `fw-audio/adsp.mdt`, and `fw-audio` is absent from this machine
  (`~fkernel` has only `fw-gpu` and `fw-wlan`), so the DSP that does charging is not in the image.
  The files must be pulled from the phone's `modem_a` (a TWRP job), then the userland image rebuilt.
- **Tearing** — expected to improve with the period fix + `fb_hz=120`; unverified.

## Logistics learned tonight (do not repeat)

- TWRP with both backlights at 0 does **not** charge this phone usefully: `usb/current_now` 500 mA,
  `battery/current_now` only ~-88 mA, capacity flat at 9% for ten minutes, then the phone shut down.
  Set the backlight only to keep the panel dark, and charge from a wall charger with the phone off.
- `usb-test.sh` keeps the loader session and the staged system image, so a repeat boot costs ~2 s of
  staging instead of ~90 s. Use it, not a fresh `fastboot boot` per iteration.

## The kernel builds again, and the 120 Hz change is in it

**Why the build was stuck.** Not the export check people kept hitting — that one is noise and it still
fails at the end of a successful build. The real break was at *link* time: `redwood_input.c` and
`loader_return` call `lemonadep_logkeep_init`, `lemonadep_wlan_init`, `lemonadep_wlan_reserve` and
`lemonadep_logkeep_return`, which live in `bsd/dev/lemonadep_logkeep.c` and `bsd/dev/lemonadep_wlan.c`.
Those files ship in `xnu/files/`, but the three lines that compile them were only ever in the working
tree's `bsd/conf/files` — never exported into the overlay, so every fresh tree failed to link. The old
tree's `bsd/conf/files` (lines 136/138/139) is now copied into `xnu/files/bsd/conf/files`, so
`xnu/apply.sh` produces a tree that builds.

```
bash xnu/apply.sh /root/fkernel/xnu-fresh/xnu-8796.121.2     # 73 changed + 118 new files
XNU_SRC=/root/fkernel/xnu-fresh/xnu-8796.121.2 bash xnu-build.sh -j6 -k
```

The build still ends with `config_all … Private.symbolset` / `Error 2` after the kernel is produced;
the binary at `BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837` is complete (12:33,
15,735,080 bytes) and boots. Previous kernel kept as `~/fkernel/mach.nov3.bak`.

**The test (2026-11-03 12:33, `cadence120.log`).** Booted with the vsync-period patch compiled in and
`fb_hz=120`. It ran the full 200 s with no faults, `metal=2`, Wi-Fi joined, GL drawing, 3220 frames.

| | frames1.log (60 Hz, no period fix) | cadence120.log (patch + `fb_hz=120`) |
|---|---|---|
| frames drawn in 200 s | 3060 | 3220 |
| CPU per frame | 3566 us | 3836 us |
| GL errors | 0 | 0 |

**So the change did not raise the frame rate** — 5 % is noise, and CPU per frame is unchanged. That is
not proof the patch is wrong: these counters measure *how often CoreAnimation draws*, which is the
apps' own redraw rate, not the panel's refresh. To settle it, the next run needs something that
reports actual vsyncs delivered (a counter in `vsync()` printed once a second, or the compositor's own
swap count) and a visual check for tearing. Until then `fb_hz=120` is an unproven change: removing
`fb_hz=120` from `lemonadep.conf` and repacking returns the phone to the exact state that was verified
working on 2026-11-03 04:44.

## Addendum: is Maps a Metal problem? No.

Checked after the GPU split landed, because "maps tiles don't work" reads like a renderer fault:

* Maps **launches and draws**. Run of 2026-11-01 11:37 (`out/hackios/metal1.log`): `Successfully spawned
  Maps[193]`, `Maps application main() started`, foreground at 11:37:41, and not one `MTL`/`Metal`/renderer
  complaint attributed to it. A missing Metal device looks different here: the earlier `metal=1` runs had
  `metal_test: the context's Metal device: nil` and a process that could not open a context at all. Maps is
  past that point — its own UI (chrome, controls) is drawn.
* The data never arrives. Measured from the phone with `net_test fetch` (`out/hackios/weathermaps1.log`):
  `gspe19-ssl.ls.apple.com` -> **403, 0 bytes**, while the same session got `200` from
  `bag.itunes.apple.com/bag.xml`. Tile requests are GeoServices-signed the way weather is Mescal-signed, and
  Apple answers unsigned ones with 403. No tiles -> nothing to draw over a working Metal context.
* So: **not Metal, not the kernel's GPU path.** A renderer cannot paint tiles it was never handed. Maps needs
  a different tile source behind a patched `GeoServices` (a much larger job than Weather, which at least has
  a keyless REST equivalent).

## The seam Weather does have: an Apple-internal Local endpoint

Weather's own `AppConfiguration` dump in `metal1.log` lists, besides Production/Staging/QA:

    WeatherCore.EndpointConfiguration(environment: Local,
        weatherDataURL: http://localhost:5033, ...)

Plain HTTP on the loopback, no Mescal, no TLS — Apple's own local-development endpoint, shipped in the
framework. That is the cheapest way in: the app can be pointed at a server of ours instead of having Apple's
signature forged. `http://localhost:5033` does **not** appear in the `Weather` app binary (checked with
`strings` on `Weather.app/Weather` from `system.apfs`), so both the URL and the selector live in
`WeatherCore.framework`, which is code-less on the volume — it ships only inside the dyld shared cache.
Selecting that environment therefore needs the key read out of the cache, or an interpose on the config
object inside the Weather process; that is the next concrete step for the Weather shim.

## The Local environment is reachable, and Weather now gets it — the app still asks for nothing

The keys are not guesses. WeatherCore's own strings, read out of the dyld shared cache
(`20F66__iPhone10,3_6/dyld_shared_cache_arm64.13`, the framework has no code on the volume), sit together
in one table:

    weather.environment.aps
    weather.environment.contentEnvironment      (values: "Production - Origin", "Local - Mock Server")
    weather.environment.localServerPort
    weather.environment.localServerURL          (beside the literal "http://localhost")

So the environment is a UserDefaults choice, not a compiled-in URL, and the port is a separate key — which
is why `localhost:5033` appears nowhere as a whole string.

**Built (experimental image, not the verified one).** `src/inject_weather.c` ->
`/redwood/lib/libredwood-weather.dylib`, injected into `Weather`, `WeatherWidget` and `weatherd`
(`etc/inject.conf`):

* a constructor sets the three keys before the framework can read them, and
* a thread listens on `127.0.0.1:5033`, writes down every request line and header, and answers with
  `/var/mobile/redwood-weather.json` if that file exists and `{}` otherwise.

Also added: `src/inject_sb.c`'s `open_demand()`, which opens the bundle id in `/var/mobile/redwood-open`
25/45/65 s after SpringBoard starts. Nothing else here can start an application without a finger on the
screen, and a hands-free test has none. (It reports `refused` from `-[LSApplicationWorkspace
openApplicationWithBundleID:]` while FrontBoard spawns the app anyway — the return value is not the answer.)

**Run `weathershim3` (250 s, `metal=2`, `fb_hz=120`, GL drawing).** 574,426 bytes, no faults, and:

    redwood: Weather: the local server is going into the environment Apple calls Local
    redwood: Weather: defaults weather.environment.contentEnvironment set
    redwood: Weather: defaults weather.environment.localServerURL set
    redwood: Weather: defaults weather.environment.localServerPort set
    redwood: Weather: the local server listens on 127.0.0.1:5033, answering /var/mobile/redwood-weather.json
    Successfully spawned Weather[41]

So the library is in the app, the keys are set, and the server is up. But **the app never asked it for
anything** (0 requests), produced no log lines of its own, and neither `weatherd` nor `WeatherWidget` was
ever spawned. That is where this stands: the environment is no longer the blocker in principle, but the
app, launched this way, does not proceed to a fetch — it is probably never activated to the foreground, and
on iOS 16 the app asks `weatherd` for the forecast rather than fetching it itself.

Next: find out whether Weather reached the foreground (SpringBoard's activation path), and whether
`weatherd` is spawned by an activation rather than by the app's own startup. `open_demand()` returning
`refused` while the app spawns is the thread to pull: FrontBoard may be doing a background/prewarm launch,
which would explain both the missing activation and the missing fetch.

### Correction to the last paragraph above: it did reach the foreground

The guess that the app stayed in the background is wrong. `backboardd[10:457]` logged
`new scene host settings: contextID:614E3988 <sceneID:com.apple.weather-default> unspecified -> foreground`
at 14:10:45, with roughly three minutes of log after it and still no request on 5033.

So the difference from the 1 November run is the environment itself. There, with no keys set, Weather fetched
and died on Mescal (`Weather[241]`, `AMSMescalFairPlay ... code=12`). Here, with the three keys set, it
fetches nothing and logs nothing — not even a Mescal error. Two readings, and one boot decides between them:

* the environment *was* taken and the endpoint is built from the keys in a shape the framework does not
  accept (`localServerURL` may want the port inside it, or the keys may be read from a domain other than the
  one the constructor writes), so no request is ever made; or
* `contentEnvironment` wants its raw value, not the display name. The shipped configuration JSON spells the
  others `"PRODUCTION"` / `"STAGING"`, while the two literals beside the keys are `"Production - Origin"` and
  `"Local - Mock Server"`. A value that does not map can leave the app with no endpoint at all.

The experiment that separates them: boot with `contentEnvironment` unset while the shim still serves 5033,
and see whether the Mescal error returns. If it does, the Local selection works and only the URL shape is
wrong; if it does not, the keys are being read from somewhere else than the domain being written.
