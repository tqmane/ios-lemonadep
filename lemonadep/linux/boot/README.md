# Boot chain for Linux on lemonadep

Two paths, both starting from the phone's own ABL. Neither has been run yet; the EFI one is the target, the
Android-boot-image one is the probe.

## A. Android boot image (probe, no flashing)

This is the path the iOS port uses and it is the lowest-risk way to get a first kernel banner:

```sh
./pack-bootimg.sh /path/to/Image.gz /path/to/sm8350-oneplus-lemonadep.dtb /tmp/linux-probe.img
fastboot boot /tmp/linux-probe.img
```

* header v3, `os_version` 16.0.0 / `os_patch_level` 2026-08 (measured from this phone's stock `boot_b`).
* `fastboot boot` only — nothing is written; a failed boot costs a power cycle.
* A mainline kernel with EFI stub will also boot from here, but with no ESP there is no dtbloader, so the DTB
  must come from the boot image (this script appends it as the second-stage DTB, which the kernel picks up).

Caveat: mainline kernels expect to find `/chosen` properties and sometimes the DTB at a specific address.
If the kernel reports "no DT" or a bare `earlycon` and nothing else, the DTB address is the first thing to
check; `pack-bootimg.sh` prints what it wrote so the numbers are in the log.

## B. UEFI + systemd-boot + dtbloader (target)

Layout of the ESP (FAT32, 512 MB is plenty):

```
/EFI/BOOT/BOOTAA64.EFI                    systemd-boot (built for aarch64, or the Armada one)
/EFI/systemd/drivers/dtbloaderaa64.efi    dtbloader, loaded by sd-boot as a driver
/loader/loader.conf                       default lemonadep.conf, timeout 3
/loader/entries/lemonadep.conf            one BLS entry (below)
/dtbloader/dtbs/qcom/sm8350-oneplus-lemonadep.dtb
/vmlinuz-lemonadep                        Image (or a UKI; see below)
/initrd.img                               initramfs from the distribution build
```

`loader/entries/lemonadep.conf`:

```
title   Luma on lemonadep (mainline)
linux   /vmlinuz-lemonadep
initrd  /initrd.img
options console=tty0 root=PARTUUID=<root-partition> rw
```

dtbloader finds DTBs in `/dtbloader/dtbs/` first, then `dtbs/`, then the root of the partition, and installs
the match into the UEFI configuration table, so the kernel inherits it even though Mu-Silicium's UEFI is not
a device-tree platform. Its per-device fixups (MAC addresses, hardware variants) are where phone-specific
values such as the Wi-Fi MAC belong.

### Built-in DTB vs. dtbloader

A mainline `Image` starts through the EFI stub and will use the DT in the configuration table if there is
one. If dtbloader is not ready, the fallback is to build the DTB **into** the kernel (CONFIG_ARM64_APPENDED_DTB
+ `make qcom/sm8350-oneplus-lemonadep.dtb` with the EFI stub) or use a UKI that embeds it. Try dtbloader first;
it is what Armada ships and it keeps the DTB updatable without rebuilding the kernel.

## C. Getting the ESP onto the phone

The iOS port writes `system.apfs` and a payload into `userdata`; for Linux the same partition is the natural
home for both the ESP and the root filesystem, but **nothing here should be flashed until a Linux kernel has
booted from RAM at least once**. The staged sequence:

1. `fastboot boot pack-bootimg.sh` output with an initramfs that brings up USB networking (P1/P3).
2. Only then create partitions and copy the ESP; verify with `fastboot boot` of the UEFI, not a flash.
3. Flashing a persistent boot image is a separate, reversible decision with a backup taken first.

## D. How to verify each step

| Step | What to look for |
| --- | --- |
| Boot image probe | kernel banner over `earlycon`; `qcom` SoC id in `dmesg`; no "Unable to handle kernel paging request" |
| UEFI reaches the ESP | Mu-Silicium's boot menu/serial shows the volume; `dtbloader` prints the device it matched |
| dtbloader installs the DT | `/proc/device-tree/compatible` contains `qcom,sm8350` and `oneplus,lemonadep` |
| systemd-boot entry | entry visible with a 3 s timeout; kernel command line as written |
| Rootfs | `root=PARTUUID` mounts; `systemd` reaches `multi-user.target` |

Every one of these is observable over USB with the scripts in `../hackios/` (`usb-test.sh` for the staged
payload loop) plus a serial console, so no step needs a human watching the panel.
