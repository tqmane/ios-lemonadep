# Linux on lemonadep: a Luma-based phone OS with Armada's boot mechanics (port plan)

Status: **plan + first artifacts**, 2026-11-03. Nothing here has booted. It exists so the next session starts
from decisions and sources instead of re-deriving them, and so the iOS port's measurements are not lost.

## 1. The decision

Run a **mainline Linux kernel** (7.x, SM8350) on the OnePlus 9 Pro, boot it through **Mu-Silicium UEFI**
(already working on this phone for the iOS port) with **dtbloader** supplying the DTB, and put a
**Luma ARM64 rootfs** on top of it. Keep **Armada's image model** (Fedora `bootc`, BLS entries, OTA updates,
EFI-first) as the packaging target, because it is the only one of the two that ships a device-porting story.

In one line: **Luma's userland + Armada's boot/image plumbing + mainline sm8350 + our measured hardware.**

Why not "port Luma as-is" or "port Armada as-is":

| Option | Verdict |
| --- | --- |
| Luma only | Its mobile device profiles are downstream hardware work; an SM8350 profile does not exist. It is also x86_64-primary today (AArch64 shares the platform tree; "presence of a profile does not establish release support"). |
| Armada only | A gaming image: Steam + FEX + Proton + KDE on a curated ROCKNIX-derived device list. It needs a working Vulkan stack before it is anything but a desktop. |
| **Both, as above** | Luma gives the phone-shaped shell (GTK/libadwaita, adaptive apps), Armada gives the image/boot/OTA discipline, mainline gives the hardware. Each piece is replaceable without redoing the others. |

## 2. Architecture

```
ABL (OnePlus bootloader, unlocked)
  └── Mu-Silicium UEFI for lemonadep          [works today: this is what boots the iOS port]
        ├── dtbloader.efi (EFI driver)         picks dtbs/qcom/sm8350-oneplus-lemonadep.dtb,
        │                                      installs it into the UEFI configuration table
        └── systemd-boot (BOOTAA64.EFI)
              └── UKI or kernel+initrd entry   linux /initrd /dtb  (mainline 7.x)
                    └── Luma ARM64 rootfs      (Fedora-based composition; Armada-style bootc image later)
```

Two boot paths, on purpose:

* **EFI path (primary).** ESP with systemd-boot, `dtbloader.efi` under `/EFI/systemd/drivers/`
  (`dtbloaderaa64.efi`), DTBs under `/dtbloader/dtbs/`. This is exactly Armada's documented mechanism and it
  is the one that survives an OS update.
* **Android boot image (fallback/probe).** `boot/pack-bootimg.sh` packs `Image` + `dtb` into a v3 boot image
  with this phone's measured `os_version`/`os_patch_level`, for `fastboot boot` when the ESP path is not
  ready. Our iOS work already boots exactly this way, so it is the low-risk route for the first kernel.

## 3. Prior art that exists (read these before writing code)

| Source | What it gives us |
| --- | --- |
| [`blahajcoding/op9pro-mainline-poc`](https://github.com/blahajcoding/op9pro-mainline-poc) | **Mainline Linux on this exact board.** Referenced in our own log: it hit the identical eGPIO wall for the touch rail (gpio197 is an SM8350 eGPIO pad that must be claimed, bit 12 set when bit 11 reads 1). Its DTS node names for the Adreno 660 firmware match what we pulled. Start here, not from scratch. |
| [`TravMurav/dtbloader`](https://github.com/TravMurav/dtbloader) | The EFI driver that installs a DTB into the UEFI configuration table, with per-device fixups; `scripts/describe_hw.sh` generates a device template from a running system. |
| [`armada-os/armada`](https://github.com/armada-os/armada) | Fedora `bootc` image assembly, systemd-boot + dtbloader boot path, `/KERNEL` for older ABLs, ROCKNIX-derived device support, OTA. Copy the *mechanics*, not the device list. |
| [`SimplyLuma/luma`](https://github.com/SimplyLuma/luma) | OS source, `config/` device profiles, `docs/platforms.md`, `BUILDING.md`, Apache-2.0. The userland and shell to target. |
| Arch Linux ARM on lemonadep (mainline 7.3, ~110 patches, reported 2026-11-02) | Proof the SoC side is far enough along to boot a desktop-oriented distro; the patch set is the thing to find and diff against upstream. |
| postmarketOS `oneplus-lemonadep` | An existing port with a known USB-networking bug on 2026-04 builds; useful as a deviceinfo reference and as a warning about what "supported" means. |

## 4. What the iOS port already contributes (measured, not guessed)

Full detail in [`../HWMAP_lemonadep.md`](../HWMAP_lemonadep.md) and
[`../hackios/FINDINGS-2026-11-01-03.md`](../hackios/FINDINGS-2026-11-01-03.md). The Linux-relevant subset:

* **UEFI on this phone works**, boots from `fastboot boot`, takes USB commands, and hands off to a payload.
  A/B slot layout, `os_version` 16.0.0, `os_patch_level` 2026-08 and the loader's payload limit are measured
  (`../BOOT_lemonadep.md`).
* **Panel**: Samsung AMB670YF01, 1080x2412, **command mode**, ABL leaves DSI autorefresh on and a splash
  plane at `0xE4D00000`; no geometry fix needed; 120 Hz works once the vsync period is right (our
  `tools/fix-vsync-period.py` explains the mistake in XNU's `vsync()`; the same off-by-a-period bug is worth
  checking in any driver that forwards timestamps).
* **Touch**: Synaptics S3908 (I²C `0x4B`) over **TCM v1/v2**, GENI SE4, on a rail that needs the eGPIO claim
  (gpio197). Digitizer extents 1440x3216, scaled to the panel.
* **Keys**: PMK8350 `PON_HLOS` (power, vol-down; gen-3 register layout) and PM8350 GPIO6 (vol-up).
* **UFS**: UFSHCI 3.0 at `0x1d84000`, 64-bit DMA, LUN 0 is `userdata`; ABL leaves the host running.
* **Wi-Fi**: this port runs Linux's own `ath11k` against the QCA6490 over PCIe, with firmware pulled from the
  phone (`amss.bin`, `m3.bin`, `bdwlan.bin`, `regdb.bin`) and the rule that **64 MB of DMA must be reserved
  before the GPU**.
* **GPU**: Adreno 660 + GMU windows, SMMU at `0x03da0000` (`dma-coherent`), GMU stream `<5 0x400>`; firmware
  set `a660_gmu.bin`, `a660_sqe.fw`, `a660_zap.*` pulled from `/vendor`.
* **Power/charging**: BQ28Z610 gauge answers over I²C; the **MP2650 charger never ACKs** (`status 0xff`), and
  charging is owned by the ADSP, whose firmware (`fw-audio/adsp.mdt`) is not in our image. Under Linux this
  maps to `qcom,sm8350-adsp-pas` + `pd-mapper` + a PMIC charger driver — expect this to be one of the harder
  pieces, and expect the charger to stay silent until the ADSP is up.
* **Hypervisor quirks**: EL1 `CNTP_CTL_EL0` writes are undefined and the virtual GIC faults
  `GICR_IPRIORITYR` writes. This is about XNU running under the hypervisor, not about Linux, but it tells you
  the phone's EL2 is doing more than the usual.

## 5. Phases, with exit criteria

| Phase | Work | Exit criterion |
| --- | --- | --- |
| **P0** (done) | UEFI boots, hardware map measured, board facts written down | this repository |
| **P1** | Build mainline 7.x for `sm8350`, boot `op9pro-mainline-poc`'s DTS via the Android-boot-image path | kernel banner over `earlycon`/USB, `fastboot boot` only, no flashing |
| **P2** | UEFI path: ESP with systemd-boot + `dtbloader.efi` + the DTB, one BLS entry | the same kernel boots through UEFI with dtbloader installing the DT (proves Armada's mechanism here) |
| **P3** | USB networking + serial console under Linux (`dwc3`, `gadget`), rootfs on a partition | `ssh`/`nc` into the phone; logs without a screen |
| **P4** | Luma ARM64 rootfs on top, first boot to a shell, then to a graphical session | GNOME/Phosh-style session on the panel, input from touch |
| **P5** | Display: `msm`/DPU + panel driver, brightness, 120 Hz | usable desktop at native 1080x2412 |
| **P6** | GPU: mainline `msm`/Adreno + Mesa **Turnip** (Vulkan), then a gamescope/Steam layer à la Armada | `vulkaninfo` on Turnip; then a game image becomes a packaging question, not a bring-up one |

Audio, modem/cellular, camera and Bluetooth are explicitly **out of scope** until P5/P6 are done; postmarketOS
already documents audio as broken on this phone.

## 6. Risks, ordered by what would stop the project

1. **Panel driver.** Mainline needs a real DPU/DSI panel driver for AMB670YF01 (command mode). This is the
   most likely multi-week item and the one our measurements help with most.
2. **Charging.** If the ADSP path is required and its firmware is not obtainable in a redistributable form,
   the phone may only charge while off. Budget for it; it is not a blocker for bring-up.
3. **GPU/Vulkan.** Turnip supports a660 (Mesa MR 10892 added it), but the kernel side must expose the GMU
   correctly. Without it, Luma runs on `llvmpipe` — usable for bring-up, useless for Armada's purpose.
4. **ABL/AVB.** Our images boot because they are `fastboot boot`ed. Anything persistent must survive AVB and
   rollback checks; flashing an ESP means touching partitions we have so far left alone.
5. **Thermals and power.** No thermal framework work has been done here; sustained load on a phone SoC
   without it will throttle or shut down.

## 7. Non-goals for now

* Modifying the iOS port to host Linux (they share the UEFI, nothing else).
* Distributing Apple, Qualcomm or OnePlus firmware. Anything pulled from the phone stays gitignored
  (`../fw-gpu/`, `../fw-wlan/`, `../fw-vendor/`).
* Promising device support upstream. A device tree that boots is a starting point, not a submission.

## 8. Immediate next steps

1. Clone `op9pro-mainline-poc` and the Arch-on-lemonadep patch set; diff their DTS against the mainline
   `sm8350.dtsi` of the kernel version we build. Record every delta in `dts-checklist.md`.
2. Build that kernel with `qcom_defconfig`-plus-fragments, produce `Image.gz` + `sm8350-*.dtb`, pack with
   `boot/pack-bootimg.sh`, and `fastboot boot` it with `earlycon` — the phone is already in the loader, so
   this is one USB cycle, hands-free.
3. In parallel, build the ESP layout from `boot/README.md` and verify that Mu-Silicium's UEFI can see a
   FAT32 partition and load `dtbloader.efi` — that is the piece Armada depends on and nobody has tested it
   on this phone yet.
