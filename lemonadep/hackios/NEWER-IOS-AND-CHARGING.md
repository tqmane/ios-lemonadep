# Newer iOS, newer phones, and where charging actually comes from

Researched 2026-11-03, while the phone charged. Everything below is sourced; the URLs are at the end
of each section.

## 1. iOS 16.5 is no longer the ceiling — iOS 18 already boots on Android

Bergamota (`ry-diffusion/bergamota`) boots the **unmodified iOS 18.7.8 (22H352) userland of an
iPhone XR** to SpringBoard on a **Poco F1** (beryllium, Snapdragon 845). Its kernel, "Heartwood", is
**xnu-11215.81.4 since 2026-10-23** — before that it was xnu-8796, the same iOS 16 generation this
port uses. Apps register, Safari and Settings open, all 8 cores run, SSH over USB CDC-ECM. Not
working: Wi-Fi, cellular, Bluetooth, audio, camera, sensors, SEP/FaceID, GPU.

The trick that matters for us is **arm64e without pointer authentication**. iOS 18 userland is
arm64e-only; Snapdragon 845 (like the 888) is ARMv8.2 and has no PAC. Bergamota's "Renegade"
rewrites every arm64e Mach-O *and the whole dyld shared cache* in place, 4 bytes for 4 bytes so no
offsets move — `RETAA`→`RET`, `BRAA`/`BLRAA`→`BR`/`BLR`, `PACIA`→`NOP`, `PACGA`→`EOR` — then re-signs
ad hoc and recomputes corecrypto's FIPS HMAC. This is a *userland image* cost, paid once per build,
not a kernel patch.

Other established ports, for the record: `dipa-studio/ios-sweet` (this project's upstream, Redmi
Note 10 Pro, iOS 16.7.16 to the home screen), `oosexgang/hakios-xnu-kernel` (Poco X5 Pro),
`MakrSas/ios-topaz` (Note 12, adds WPA2 and Adreno 610 via Mesa), `aTechGeekDev/ios-apollo`.

**iOS 17:** no public Android boot found. Projects went 16 → 18.

**iOS 26:** not on hardware. xnu-12377 (Darwin 25) runs to a framebuffer in QEMU per community
reports; ChefKiss Inferno boots real iOS only on *Apple Silicon* (iPhone 11 emulation), and even
there iOS 26 is not the tested path.

https://github.com/ry-diffusion/bergamota · https://github.com/dipa-studio/ios-sweet ·
https://github.com/oosexgang/hakios-xnu-kernel · https://github.com/ChefKissInc/Inferno/issues/241

## 2. Which XNU is which iOS, and who built it off-Apple

| tag | iOS generation | built for non-Apple hardware by |
|---|---|---|
| xnu-8796.x | iOS 16 | ios-sweet, ios-topaz, ios-apollo, HakiOS, **this port** |
| xnu-10002.x | iOS 17 | nobody found |
| xnu-11215.81.4 | iOS 18 | **Bergamota** (Snapdragon 845) |
| xnu-11417.x | iOS 18 point releases | 〃 |
| xnu-12377.x | iOS 26 | QEMU bring-up only |

All of these still need Apple's clang/toolchain to build, which is why the Android ports build their
kernels on macOS CI runners.

## 3. What actually blocks iOS 17+, and what doesn't

**Bypassed by every port (so not the wall):**
- *SSV / APFS seal.* No port mounts a sealed volume. ios-sweet's `tools/mkiosroot.sh` copies the OS
  volume **and both cryptexes** into one case-sensitive journaled **HFS+** volume with a plain system
  keybag; Bergamota's `renegade fetch` pulls root dmg + SystemOS/AppOS cryptexes decrypted and writes
  its own HFS+ root. This is also why keychain and data protection don't work.
- *im4m / apticket.* Never checked, because iBoot never runs: ABL → shim/Enxerto → XNU with a
  self-built Apple Device Tree. ios-sweet uses the "Hactivation" path of `mobileactivationd` chosen
  through device-tree security status — no Apple server involved. Bergamota spoofs `/product` from a
  real iPhone X device tree.

**The real barriers:**
- **SPTM / TXM (iOS 17+).** iOS 17 shipped `sptm.t8120.release.im4p` and
  `txm.iphoneos.release.im4p`. TXM runs at GL0 and *takes over code-signing enforcement from AMFI*;
  SPTM runs at EL2 and XNU calls into it from pmap. There is no non-Apple equivalent, so ports keep
  AMFI permissive and supply their own kernel — which works, but means the userland must be
  pre-rewritten (Renegade).
- **arm64e / PAC**, as above.
- **Per-SoC driver grind** — the same work this port has been doing, per phone.

**The genuinely impossible wall:** Apple's servers. No project gets an Apple ID, activation,
iMessage, App Store, Maps or Weather — HakiOS's own comparison page says "None of the four is an
iPhone to Apple's servers." That is FairPlay/attestation, not kernel work (see §5).

https://df-f.com/blog/ios17 · https://hackios-web.vercel.app/en/docs/comparison

## 4. Newer phones: UEFI exists, XNU does not

Mu-Silicium (the UEFI this phone boots) now covers much newer hardware — OnePlus 15 / 15R
(8 Elite Gen 5 / 8 Gen 5), OnePlus 13 and 13s (8 Elite), Redmi K90, OnePlus 13R/Ace 5 (8 Gen 3),
Poco F6, Galaxy S23+ (8 Gen 2), Nothing Phone (2) — with display+storage+often Linux booting. Latest
release v4.1 (2026-11-01). **No Google Tensor device appears at all.** But UEFI support is only the
prerequisite: nobody publicly boots XNU on any 8 Gen 1/2/3/Elite phone, and the newer SoCs add work
(16K-page handling already parks cores on Bergamota; these have more of it).

https://raw.githubusercontent.com/Project-Silicium/Mu-Silicium/main/Status.md ·
https://github.com/Project-Silicium/Mu-Silicium/releases

**Realistic path from here to iOS 18:** xnu-11215 kernels exist and one has been built for a
Snapdragon, and the arm64e rewriting is a solved (if large) tooling problem. It is a userland
re-hosting job plus a kernel rebase from 8796 to 11215 — a fork's worth of work, not a patch.

## 5. FairPlay / Mescal: the wall is hardware, but Weather is solvable

`fairplayd` needs the **UID key** (per-chip, fused, never leaves the AES engine) and the **GID key**
(per-SoC-family) plus a SEP-rooted device certificate chain. None of these exist on a Snapdragon. So
a Mescal signature Apple's servers accept is impossible — not unimplemented. Corellium, with a real
ARM hypervisor and a commercial budget, states plainly that its virtual devices "do not support any
Apple services, including iCloud, the App Store, iMessage, Siri, **Apple Maps**" and do not run
FairPlay-encrypted apps; their workaround is to decrypt on a physical jailbroken iPhone and re-sign,
i.e. avoid FairPlay rather than emulate it.

**But Weather does not have to use Mescal.** WeatherKit has a public REST API authenticated with an
**ES256 JWT signed by your own Apple Developer `p8` key** (`iss`/`sub`/`kid`) — ordinary crypto, no
SEP, no device identity. A small local shim (token cached ~1 h) can serve Apple's `v1` JSON shapes,
and the Weather app's data provider can be pointed at it. That removes Mescal from the Weather path
entirely. Maps vector tiles are authenticated differently and have no public equivalent — that one
stays broken unless `GeoServices` is patched to another tile source (OSM/MapTiler).

https://support.corellium.com/features/apps/testing-ios-apps ·
https://support.corellium.com/troubleshooting-faqs/general-faqs ·
https://developer.apple.com/documentation/weatherkitrestapi

## 6. Charging: the ADSP belief was half wrong, and the chip is on I2C

The port's notes say charging is the audio DSP's battery manager and that `fw-audio/adsp.mdt` is
required. Half of that is right: on SM8350 the *stock Qualcomm* path does run a charger PD on the
ADSP (`pmic_glink` matches `PMIC_RTR_ADSP_APPS`, looks up `msm/adsp/charger_pd` via `tms/servreg`,
and `qcom_battmgr` talks to it; every read is a `pmic_glink_send()` round trip, not a register read).
That is why Linux mainline and postmarketOS need `adsp.mdt` plus a `pd-mapper`.

But on **this phone** the wired charger is not the PMIC's SMB5 at all — it is an **MPS MP2650 on
I2C**, and Android drives it directly from the AP. Read off the device in TWRP (2026-11-03):

```
7-005c  mp2650-charger     <- the charger
7-0051  hl7227-cp          <- the 65 W charge pump
8-0055  bq27541-battery    <- the BQ28Z610 gauge
6-005a  aw8697_haptic      (0x5a is the haptics driver, not a charger)
```

bus 7 is `qupv3_se0` (gpio4/5) and bus 8 is `qupv3_se2` (gpio12/13) — exactly the buses
`redwood_gauge.c` already bit-bangs. So charging is a register-programming problem on a chip this
kernel already reads, not a firmware problem. Two things are missing:

1. **`redwood_gauge.c` never writes.** Its header says so: "NOTHING IS WRITTEN TO EITHER CHIP". It
   reads the MP2650's status and ADC registers and cannot set the input current limit or re-enable
   charging.
2. **The chip's watchdog.** The port's note is that the charger runs on "its own defaults once its
   watchdog has run out (Android is not there to kick it)". A charger whose watchdog expired is
   disabled until something re-enables it — which matches the measurement exactly: ~0 mA on USB, and
   -300…-500 mA when the phone is loaded.

So the fix is a small charger bring-up in `redwood_gauge.c`: a bus **write** helper, then (behind a
boot-arg, off by default) re-enable charging, set a conservative input current limit, and pet the
watchdog — leaving float voltage alone, since this is a dual-cell 4500 mAh pack and the vendor's
float profile is not something to guess.

https://raw.githubusercontent.com/torvalds/linux/master/drivers/soc/qcom/pmic_glink.c ·
https://raw.githubusercontent.com/torvalds/linux/master/drivers/power/supply/qcom_battmgr.c

## 7. Weather and Maps, measured on the phone instead of argued about

`hackios/rc.jobs.weathermaps` is a boot scenario (`RC_JOBS=rc.jobs.weathermaps`, the job
`com.redwood.demo` runs it) that asks the same questions a stock app asks, in order, and prints the
answers. Run 2026-11-03 12:48 (`out/hackios/weathermaps1.log`):

```
net_test: waitaddr en0: an address after 37.1 s
net_test: en0: inet 192.168.0.22 netmask 255.255.255.0
net_test: resolve weather-data.apple.com, 0.02 s: 2.23.154.115 ... (9 addresses)
net_test: resolve gspe19-ssl.ls.apple.com, 0.04 s: 146.75.3.47
net_test: reach weather-data.apple.com: flags 0x2: reachable
```

| request | what Apple answered |
|---|---|
| `https://bag.itunes.apple.com/bag.xml` (control) | **200**, `x-set-apple-store-front: 143500-2,8` |
| `https://weather-data.apple.com/v3/weather/en_US/45.25/19.84` | **401**, 25 bytes, 0.25 s |
| `https://gspe19-ssl.ls.apple.com/` (Maps tile host) | **403**, 0 bytes, 0.29 s |

That settles it. DNS, TCP, TLS, the trust store and trustd all work — the control request comes back
200 with Apple's own store-front header. Weather returns **401** and Maps' tile host returns **403**:
Apple recognises both requests and refuses them, because they carry no signature it will accept. So the
Weather app shows no numbers because it gets no data, not because it cannot draw them, and Maps tiles are
refused at the same layer. This is the Mescal wall reached at the network edge rather than argued from a
crash — the one place it can actually be observed.

**Correction to the record.** `userland/mkjobs.py` carries a note saying the empty App Store and Weather
"were never its doing" and pointing at the network section. That note is about the *store bag and
storefront* path (where the failure really is "the local account doesn't have a storefront"), and it also
warns — correctly — that `/dev/console` drops lines, so no conclusion can rest on a missing log line.
This measurement is what a conclusion can rest on, and it says the weather request itself is refused by
Apple.

**Where that leaves each one.** Weather is still fixable without FairPlay, because WeatherKit's public
REST API takes a developer-signed ES256 JWT (§5) — a shim can feed the app real data, and the digits will
render because nothing about the renderer is broken. Maps cannot: the tile service has no public
equivalent, so it needs another tile source behind a patched `GeoServices`.

**Also measured in that run** (the battery line, verbatim):

```
battery: gauge ok: 95%, 8190 mV, -365 mA, 36.7 C, flags 0xc0, 1392 of 1477 mAh (design 2220), 1442 cycles;
         charger NOT ANSWERING: status 0xff faults 0xff ... 0+22 reads not acknowledged
```

### The exact failure, from the app's own log

`out/hackios/metal1.log` (2026-11-01, `applog=1 applog_name=Weather`), verbatim:

```
WeatherWidget[114:1625] [general] AMSMescalFairPlay: [150FA57E] Init failed: { Error domain=AMSErrorDomain, code=12
WeatherWidget[114:1625] [WeatherDataService] Error while creating local signature.
    requestIdentifier=0751D8DC-…, error=Error Domain=AMSErrorDomain Code=12 "Mescal Failed"
    UserInfo={NSLocalizedDescription=Mescal Failed, NSLocalizedFailureReason=Failed to fetch hardware info}
WeatherWidget[114:1625] [WeatherService] Encountered an error when fetching weather data subset;
    location=<+45.25705602,+19.76215635> …, error=AMSErrorDomain 12 "Mescal Failed" …
```

The chain is therefore complete and every link is measured:

1. `AMSMescalFairPlay` init fails with **code 12, "Failed to fetch hardware info"** — it wants device
   identity that a Snapdragon cannot provide.
2. So `WeatherDataService` cannot create the **local signature** and gives up — the request is not
   merely rejected, it is never sent. (Which is why a bare unsigned fetch of the same URL from
   `net_test` gets 401: that is what Apple says to anything without the signature the app also
   cannot make.)
3. Weather has no data, so it has no numbers to draw. **Nothing about the renderer is involved** —
   the digits are missing because the forecast never arrived.
4. Maps is the same class one step later: its tile host answers **403** to an unsigned request.

And the most useful thing in `userland/src/inject_fairplay.c` is a negative result that closes the
obvious-looking fix: `fairplayd` **never calls IOKit at all**. Watched over three runs, it makes zero
`IOServiceMatching`, `IOServiceOpen` or `IOConnectCallMethod` calls, opens only CoreFoundation feature
flags, and leaves by *returning from `main`* — the decision is inside obfuscated code that cannot be
interposed. Its entitlement names `com_apple_driver_FairPlayIOKitUserClient`, but an entitlement is
permission, not behaviour. So writing a FairPlayIOKit kernel stub would never be reached, and no kernel
work produces a signature Apple accepts. The only route is to stop needing Mescal: replace the *data
source*, which is what the WeatherKit REST shim (a developer ES256 JWT, §5) does. Maps has no such
route — its tiles must come from another provider behind a patched `GeoServices`.

So the MP2650 does not answer **under XNU either** — `0xff` is the bus reading all ones with 22 NACKs —
matching `i2cdetect` in TWRP showing `--` at 0x5c while the driver held 0x51. Before any watchdog or
current-limit work, the charger has to answer: that is a bus/power question (is its rail up, is it held
in shutdown, is the SE clock running, is 0x5c the right address), not a firmware one. The gauge itself is
fine and reads 95%, 8.19 V, 1442 cycles.
