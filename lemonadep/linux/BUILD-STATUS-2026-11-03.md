# Linux build status — 2026-11-03

First real artifacts for the Luma/Armada-style port, built end to end on this machine.
No phone was attached during the build, so **nothing has been booted yet**.

## What exists now

| Artifact | Size | Notes |
|---|---|---|
| `Image.gz` | 14 MB | Linux 6.7.0, sm8350-mainline `dev` @ `dc758a44` |
| `sm8350-oneplus-lemonadep.dtb` | 87 KB | builds clean, incl. eGPIO/touch/GPU nodes |
| `initramfs.cpio.gz` | 3.9 MB | Alpine minirootfs + USB-ACM console + root shell |
| `boot.img` | 18 MB | Android header v3, `os_version 16.0.0`, `os_patch_level 2026-08` |

Rebuild with `scripts/build-kernel.sh`; it fetches the tree, configures, builds, makes the
initramfs and packs the image.

## Source tree: why sm8350-mainline and not kernel.org

`linux-v6.7-rc3.tar.gz` from kernel.org does compile the kernel (14 MB `Image.gz`), but it
**cannot build the lemonadep DTB**:

1. `sm8350-oneplus-common.dtsi` includes `dt-bindings/iio/qcom,spmi-adc7-smb139x.h`, absent in mainline.
2. After fetching that header, `dtc` rejects the file at line 1000 — the downstream DTS uses
   syntax newer than 6.7-rc3's dtc.

The sm8350-mainline tree is therefore the base. Its `dev` HEAD is `dc758a448b70dab6bdf38b976ef8fc81b1d0e169`
(note: *not* `0ded4eba2dab`, which is the commit the PoC writeup was based on; dev has moved on).
It already contains the board DTS, the touch driver and the eGPIO pinctrl work, so PoC patches
`0002`–`0005` are redundant there.

GitLab's archive endpoint works with a **full 40-char SHA**; a short SHA returns 404, and
`git clone` of this tree repeatedly failed in WSL with `fetch-pack: invalid index-pack output`.
The reliable path is: `git ls-remote` for the SHA, then `curl` the archive on Windows, then read
it in WSL from `/mnt/d`.

## Build gotchas hit (all resolved)

- **Two concurrent `make -j6` runs on one tree** corrupt `.o`/`.d` files; symptoms are
  `fixdep: error opening file: … .o.d` and `ar: … .o: No such file or directory` on files that
  have no compiler errors. One build at a time; a plain rerun repairs the damaged files.
- `scripts/config --enable DRM_MSM` did not force `=y` (it stayed `=m`); appending a config
  fragment to `.config` and running `olddefconfig` is what actually works.
- `set -e` plus a non-matching `grep` killed an earlier build script silently after the DTS step.
- Host deps needed: `libssl-dev libelf-dev bc cpio bison flex`; 8 GB swap added on top of 7 GB RAM.

## The observation problem

There is no UART, and mainline has **no DSI panel driver** for the 1440x3216 `amb670yf01`
panel — only `simpledrm`, which needs a firmware framebuffer that exists only on the UEFI boot
path (Mu-Silicium), not on a raw `fastboot boot` of a Linux image.

So the boot image is instrumented for a headless boot instead: the initramfs creates a USB
CDC-ACM gadget, dumps `dmesg` to `/dev/ttyGS0`, then runs a getty there. If the kernel reaches
userspace, the phone appears as a serial port on the PC and prints its own log. If it dies
earlier, the boot is silent — that failure mode is indistinguishable from "did not boot" until
the UEFI path or a panel driver exists.

## Not done

- Never booted; phone was disconnected for the whole session (`fastboot devices` / `adb devices` empty).
- No module build (`make modules`) — everything needed for first boot is built in.
- Touch (`synaptics_tcm_oncell`) is present in this tree but unverified; eGPIO claim bit 12 on
  `gpio197` is the known workaround from the PoC.
- No Wi-Fi (`ath11k` needs firmware + board file), no audio, no camera, no real DSI panel driver.

## Next step

Plug the phone in, `adb reboot bootloader`, then:

```sh
fastboot boot build/lemonadep-boot.img
```

Then watch for a new serial port on the PC (device manager: "Lemonadep Debug Console") and read
its output. The image is RAM-only; the Android install is untouched, and a power cycle returns
to Android.
