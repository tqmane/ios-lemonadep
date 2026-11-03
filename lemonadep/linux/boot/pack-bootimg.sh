#!/usr/bin/env bash
# Pack a mainline Linux kernel + device tree into an Android boot image v3 for lemonadep, so it can be
# tried with `fastboot boot` (nothing is flashed). This is the probe path in boot/README.md.
#
#   ./pack-bootimg.sh Image.gz sm8350-oneplus-lemonadep.dtb out.img [initramfs.cpio.gz]
#
# The optional 4th argument (or RAMDISK=...) embeds an initramfs. With no DSI panel driver in
# mainline, an initramfs that brings up a USB CDC-ACM gadget and logs dmesg to ttyGS0 is how a
# headless boot becomes observable; pass CMDLINE="console=ttyGS0 ..." for that path.
#
# os_version / os_patch_level are the values measured from this phone's stock boot_b (see
# ../BOOT_lemonadep.md); ABL's rollback check is what they satisfy. MKBOOTIMG= overrides the tool.
#
# The kernel command line: earlycon is what makes a silent boot diagnosable, and tty0 keeps the panel
# console for later. Add root=/initrd arguments yourself for an initramfs boot (CMDLINE=...).
set -eu

KERNEL=${1:?usage: pack-bootimg.sh KERNEL DTB OUT}
DTB=${2:?usage: pack-bootimg.sh KERNEL DTB OUT}
OUT=${3:?usage: pack-bootimg.sh KERNEL DTB OUT}
RAMDISK=${4:-${RAMDISK:-}}

OS_VERSION=${OS_VERSION:-16.0.0}
OS_PATCH_LEVEL=${OS_PATCH_LEVEL:-2026-08}
PAGESIZE=${PAGESIZE:-4096}
CMDLINE=${CMDLINE:-"console=tty0 earlycon"}
MKBOOTIMG=${MKBOOTIMG:-python3 /opt/aosp-mkbootimg/mkbootimg.py}

for f in "$KERNEL" "$DTB"; do
	[ -f "$f" ] || { echo "pack-bootimg.sh: no such file: $f" >&2; exit 1; }
done
command -v python3 >/dev/null || { echo "pack-bootimg.sh: python3 is needed for mkbootimg" >&2; exit 1; }

RAMDISK_ARG=""
if [ -n "$RAMDISK" ]; then
	[ -f "$RAMDISK" ] || { echo "pack-bootimg.sh: no such ramdisk: $RAMDISK" >&2; exit 1; }
	RAMDISK_ARG="--ramdisk $RAMDISK"
fi

# shellcheck disable=SC2086
$MKBOOTIMG \
	--header_version 3 \
	--pagesize "$PAGESIZE" \
	--os_version "$OS_VERSION" \
	--os_patch_level "$OS_PATCH_LEVEL" \
	--kernel "$KERNEL" \
	--dtb "$DTB" \
	$RAMDISK_ARG \
	--cmdline "$CMDLINE" \
	--output "$OUT"

echo "pack-bootimg.sh: $OUT ($(stat -c %s "$OUT") bytes)"
echo "  kernel   $KERNEL"
echo "  dtb      $DTB"
echo "  ramdisk  ${RAMDISK:-(none)}"
echo "  os       $OS_VERSION / $OS_PATCH_LEVEL, pagesize $PAGESIZE"
echo "  cmdline  $CMDLINE"
echo
echo "try it with: fastboot boot $OUT"
echo "read it back with: python3 /opt/aosp-mkbootimg/unpack_bootimg.py --boot_img $OUT"
