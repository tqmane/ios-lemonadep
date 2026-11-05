# App Store / Apple ID bring-up plan — OnePlus 9 Pro (lemonadep)

Date: 2026-11-05. Target: iOS 16.7.16 / iPhone X userland on OnePlus 9 Pro (SM8350). This is a research plan, **not** a claim that Apple services work. No credentials, firmware, IPSW contents, activation records, or device identity secrets belong in git.

## Grounded baseline

- The repo's `README.md` and `lemonadep/README.md` report a working on-device lock screen, home screen, touch and buttons (2026-10-23). Adreno 660 GMU/SMMU bring-up is ongoing; Metal is not implemented.
- `lemonadep/m2-boot-build.sh` sets `sweetusb=0`. The existing `tools/sweet-usbnet.sh` is a **host-side USB ECM IP/log helper**, not an Internet-sharing service. USB on lemonadep is not yet validated.
- `tools/mkiosroot.sh` builds from the Apple-supplied OS / SystemOS / AppOS images. `tools/sweet-root-tweaks.py` changes launchd and brings up activation and SpringBoard; it does **not** implement Apple ID or App Store authentication.
- Do not assume that AppStore.app is installed in the built root. The current README says it is absent, but the image itself must be checked before changing any code.
- For comparison, HakiOS's public `userland/mkjobs.py` has measured that `appstored`, `itunesstored`, and `nsurlsessiond` can make the App Store **open and display a loading spinner**. It explicitly does not prove catalog loading or app installation. The HakiOS team's 2026-11-03 announcement claims Apple ID 2FA/token persistence, while also saying iCloud and App Store remain blocked. Do not treat announcement-only work as a reusable public patch.

References:
- https://github.com/oosexgang/hakios-xnu-kernel/blob/main/userland/mkjobs.py
- https://github.com/oosexgang/hakios-xnu-kernel/blob/main/README.md
- https://t.me/oosexgangdevs/163

## Milestones and acceptance gates

### A. Offline iOS root inventory (safe, no phone needed)

1. Assemble the root using the existing tools, mount the HFS+ image **read-only for auditing**, and run:
   ```sh
   python3 tools/ios-service-audit.py /mnt/iosroot
   python3 tools/ios-service-audit.py /mnt/iosroot --json > /tmp/lemonadep-services.json
   ```
2. Record whether an app bundle with `CFBundleIdentifier=com.apple.AppStore` exists, and whether the stock launchd job definitions for `appstored`, `itunesstored`, `amsaccountsd`, `akd`, `accountsd`, `apsd`, `nsurlsessiond`, `trustd`, `mDNSResponder`, `mobileactivationd`, and `installd` exist. **Presence does not mean successful launch.** Missing labels may use different names on this iOS build.
3. Inspect the local App Store's dependency graph and dylib resolution **before** patching or transplanting anything. Only use Apple files sourced lawfully on the user's own machine. Do not distribute Apple binaries or alter signed assets in this repository.
4. Preserve a SHA-256 manifest of the untouched root and a second manifest after the repo's root tweaks. Do not add credentials or activation-token samples to either.

**Pass A:** inventory saved; exact application and daemon gaps documented with their source paths.

### B. Network first (critical path)

1. Bring up a **diagnostic** USB ECM path on lemonadep. The `sweetusb=0` setting is intentional; do not blindly flip it to `2` and assume Snapdragon 888 DWC3/PHY/UDC register layouts match sweet. Probe the SM8350 USB DT and verify DWC3 clocks, address, EP0 enumeration, and Ethernet link on-device. Keep this isolated from GPU changes.
2. After enumeration, use the host helper to set `192.168.7.1/24` on the PC side. Confirm the device has an address and that XNU's configd sees the interface and adds a route. The helper alone provides **neither DNS nor NAT**.
3. Supply a real Internet path: host routing/NAT (plus DNS configuration on the device), or a separate verified SM8350 Wi-Fi port. Verify **in this order**: local ping/link, DNS lookup, HTTPS/TLS to a benign test endpoint, then Apple service endpoints using the device's stock network stack.
4. Gather a bounded diagnostic log using the existing persistent log ring / network trace patches. Never capture or publish authorization headers, account cookies, GrandSlam tokens, Apple IDs, device serials or unredacted request bodies.

**Pass B:** traffic leaves the device and a known HTTPS request succeeds. Merely creating an interface or reaching the PC does not pass.

### C. Local App Store UI and daemon graph

1. Only if the app bundle is present: launch App Store locally and record the first failure (missing framework, XPC/Mach service, process crash, GPU/render issue).
2. Preserve stock launchd jobs wherever possible. Inspect `com.apple.appstored` / `itunesstored`, `amsaccountsd`, `nsurlsessiond`, `akd`, `apsd`, `trustd`, `mDNSResponder` and activation services. Ensure the service is actually advertised and answers XPC, not just that a process with that name exists.
3. Do not replace service responses with hardcoded fake "success". Distinguish a local spinner, server-driven catalog content, and storefront/account state.

**Pass C:** App Store launches, its required processes do not crash-loop, and logs show which remote request or local dependency remains unsatisfied.

### D. Apple ID authentication (experimental and separate)

1. The current AppleKeyStore is a stub and there is no real Apple SEP. Inventory keychain, accounts, trust, and activation dependencies and determine which ones must persist across reboot. Apple's actual server acceptance cannot be inferred from a local UI.
2. Do not copy authentication tokens from another device or spoof hardware-backed credentials. Use only a dedicated test Apple Account, genuine interactive login, and server-returned results.
3. Confirm 2FA, persistence across reboot, revocation/log-out, and handling of failed authentication before claiming success. Keep tokens and passwords out of logs, CI, commits, and bug reports.

**Pass D:** real authorized test-account login, after a reboot, without insecure token transplantation. Not currently demonstrated for lemonadep.

### E. Actual free-app download and installation (later)

1. Confirm App Store catalog/bag/storefront responses, then check FairPlay and purchase-account requirements, `installd` / MobileInstallation, code signature enforcement and launch policies.
2. Trial with a freely downloadable app that the test account is authorized to obtain. Record distinct gates: catalog loads → account accepted → download starts → bytes received → signed install completes → app launches.
3. Do not claim functional App Store support from the spinner, a download request, or permissive AMFI alone.

**Pass E:** a genuinely downloaded app survives reboot and launches. There is currently **no evidence** this passes.

### F. GPU (parallel usability track)

Finish GMU memory/SMMU checks, ring/submit/fence, then GPU userspace and Metal only after the hardware test stages are stable. CPU rendering may be sufficient to debug an App Store launch, but not to guarantee third-party app usability.

## Engineering order / suggested PR boundaries

1. This PR: offline inventory tool + tests + this roadmap. No device modification.
2. Dedicated PR: lemonadep USB ECM enumeration and diagnostics, feature-gated via boot args; validate against live logs.
3. Separate PR: host NAT/DNS recipe and **on-device** HTTPS smoke test.
4. Separate PR: AppStore bundle and daemon dependency analysis, with reproducible log identifiers and without account secrets.
5. Separate PRs: authentication state handling and install pipeline *only if legitimately reproducible*.

## Safety and licensing

The project uses a permissive AMFI/Sandbox configuration and a stub key store. It is **not suitable for a primary Apple Account or personal data**. Running iOS on non-Apple hardware raises Apple software-license issues. Keep all Apple system files, Qualcomm firmware, personal identifiers, test credentials, signing keys, session cookies and auth tokens outside source control.

The existing procedure flashes the iOS image into `userdata`, erasing Android user data. The inventory utility does not flash or mutate anything. Always preserve partition backups and ask explicitly before destructive on-device actions.
