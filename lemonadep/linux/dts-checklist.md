# Device-tree checklist for lemonadep (mainline)

Every value below was measured on this phone or read from a pinned source; the point of the table is to say
**what still has to be confirmed against the kernel version being built**, so nobody writes a DTS from
memory. Upstream `sm8350.dtsi` supplies the SoC half; the board half is this list.

## 1. Already known, and where it came from

| Area | Value we have | Source in this repo |
| --- | --- | --- |
| SoC | SM8350 (`lahaina`), 4×A55 + 3×A78 + 1×X1 | `../HWMAP_lemonadep.md` |
| RAM | `0x80000000+0x39700000`, `0xc0000000+0x1c0000000` (8 GB) | same, §1 |
| Panel | Samsung AMB670YF01, 1080×2412, **command mode** (DSC), splash at `0xE4D00000` | same, §2 |
| UFS | UFSHCI 3.0 at `0x1d84000`, 64-bit DMA, LUN 0 = `userdata` | same, §3 |
| Touch | Synaptics S3908, I²C `0x4B`, **TCM v1/v2**, GENI SE4 (`0x990000`), reset/power on gpio20/21 bit-banged + rail on **eGPIO gpio197** (claim bit 12 when bit 11 reads 1) | same, §6 + `HANDOFF-log.md` |
| Digitizer extents | 1440×3216, scaled to the panel | `HANDOFF-log.md` (touch section) |
| Keys | PMK8350 `PON_HLOS` gen-3 (power, vol-down), PM8350 GPIO6 (vol-up) | `../HWMAP_lemonadep.md` §5 |
| Wi-Fi | QCA6490 over PCIe, Linux `ath11k`; firmware `amss.bin`, `m3.bin`, `bdwlan.bin`, `regdb.bin` from the phone | `hackios/FINDINGS-2026-11-01-03.md` §11 |
| GPU | Adreno 660 (`a660` family), GMU windows `0x03d6a000`/`0x03de0000`/`0x0b290000`, GPU `0x03d00000`, SMMU `0x03da0000` (`dma-coherent`), GMU stream `<5 0x400>` | `../HWMAP_lemonadep.md` §8 |
| GPU firmware | `a660_gmu.bin`, `a660_sqe.fw`, `a660_zap.{mdt,b02,...}` from `/vendor` | `../fw-gpu/pull.sh` |
| Charging | BQ28Z610 gauge answers; **MP2650 does not ACK**; charging owned by ADSP | `hackios/FINDINGS-2026-11-01-03.md` §6 |
| ADSP firmware | `fw-audio/adsp.mdt` needed for `adsp=1`; absent from our image | same |
| Boot | A/B, `os_version` 16.0.0, `os_patch_level` 2026-08, v3 boot image accepted | `../BOOT_lemonadep.md` |

## 2. What must be confirmed, node by node

Mainline node names are given as the usual upstream spelling; **verify each against the kernel tree in use**
before adding it, because sm8350's upstream support is uneven.

| Node | What to establish | How |
| --- | --- | --- |
| `&tlmm` | GPIO numbering for touch reset/power (20/21), the eGPIO pad (197) claim, volume-up on PM8350 GPIO6 | `op9pro-mainline-poc` DTS + our `HWMAP` values; confirm with `gpioinfo`/`/sys/kernel/debug/pinctrl` |
| `&i2c*` (GENI SE4) | Which QUP is SE4 on this board, and whether the touch node needs `qcom,geni-i2c` pinctrl | compare with upstream `sm8350.dtsi` labels; read `dmesg` for the i2c controller that appears |
| `&spmi` / `pmk8350` | `pon` subnode, gen-3 register layout, `pm8350-gpios` for vol-up | upstream `pmk8350.dtsi` + our patch `1004-lemonadep-keys-gen3-pon.patch` |
| `&dsi0` + panel | Panel compatible string, DSC configuration, reset/`vdd`/`vddio` supplies, backlight (DCS 0x51 on this panel) | the panel driver may not exist upstream: this is the P5 work item |
| `&ufshc` | `vcc`, `vccq`, `vccq2` regulators and the reset GPIO | upstream + vendor DT; our UFS facts in `HWMAP` §3 |
| `&pcie0`/`&pcie1` | Which controller the QCA6490 sits on, `perst` GPIO, regulators, and the 64 MB DMA reservation lesson | our `1008-lemonadep-wlan-pcie.patch` + ath11k firmware path |
| `&gpu` / `&gmu` | `zap-shader` firmware names, `qcom,gmu` phandle, SMMU stream mapping `<5 0x400>` | upstream `sm8350.dtsi` a660 nodes + our `HWMAP` §8 |
| `&adsp` | `firmware-name`, `qcom,halt-regs`, and the `pd-mapper` requirement for charger/audio | postmarketOS notes + `NEWER-IOS-AND-CHARGING.md` |
| `&usb_1` (dwc3) | `dr_mode`, PHY, and whether the port is the one ABL leaves configured | our USB notes (`HWMAP` §9) |
| `chosen` | `bootargs`, and where the DTB is expected | depends on the boot path (`boot/README.md`) |

## 3. Things that bit us on iOS and will bite here

* **The eGPIO claim.** Without setting bit 12 on the pad whose bit 11 reads 1, the touch rail never comes up
  and the bus answers nothing. `op9pro-mainline-poc` hit the same wall; check whether mainline's pinctrl
  driver already claims it for this board or whether a fixup is needed.
* **DMA reservation before the GPU.** 64 MB reserved ahead of GPU memory was required for Wi-Fi to work in
  our kernel; mainline's reserved-memory layout may or may not account for it.
* **Command-mode panel.** Frames are pushed by the display controller; a driver that assumes video mode will
  show nothing and look like a dead panel.
* **`/var`-style persistence is not a thing here.** Unlike the iOS port, Linux owns its root filesystem;
  decide the partition layout once, before writing anything.
