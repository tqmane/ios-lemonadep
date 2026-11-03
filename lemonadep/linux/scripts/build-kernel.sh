#!/usr/bin/env bash
# Build a mainline Linux kernel + device tree + debug initramfs + Android boot image for the
# OnePlus 9 Pro (lemonadep), for `fastboot boot` only (nothing is flashed).
#
# Verified 2026-11-03 on WSL2 Ubuntu (6 cores / 7 GB + 8 GB swap). Produces:
#   Image.gz            14 MB   (6.7.0, SM8350 dev tree)
#   sm8350-oneplus-lemonadep.dtb  87 KB
#   initramfs.cpio.gz  3.9 MB    (Alpine minirootfs + USB-ACM debug console)
#   boot.img            18 MB    (header v3, os_version 16.0.0 / 2026-08)
#
# Why this source tree and not v6.7-rc3 from kernel.org: the board DTS and the SM8350 drivers
# (synaptics_tcm touch, GMU/Adreno, eGPIO pinctrl, the smb139x adc bindings) live in the
# sm8350-mainline tree. A plain 6.7-rc3 tree compiles the kernel fine but fails to build this DTB
# (missing dt-bindings/iio/qcom,spmi-adc7-smb139x.h, then DTS syntax newer than its dtc).
#
# Usage:  TREE=$HOME/linux2 ./build-kernel.sh
set -eu

TREE=${TREE:-$HOME/linux2}
JOBS=${JOBS:-6}
OUT=${OUT:-$HOME/out}
BASE_URL=${BASE_URL:-https://gitlab.com/sm8350-mainline/linux/-/archive/dc758a448b70dab6bdf38b976ef8fc81b1d0e169/linux-dc758a448b70dab6bdf38b976ef8fc81b1d0e169.tar.gz}

export ARCH=arm64
export CROSS_COMPILE=${CROSS_COMPILE:-aarch64-linux-gnu-}

host_deps() {
	command -v aarch64-linux-gnu-gcc >/dev/null || sudo apt-get install -y gcc-aarch64-linux-gnu
	for p in bc bison flex libssl-dev libelf-dev cpio rsync; do
		dpkg -s "$p" >/dev/null 2>&1 || sudo apt-get install -y "$p"
	done
}

fetch_tree() {
	[ -d "$TREE" ] && { echo "using existing tree $TREE"; return; }
	mkdir -p "$TREE"
	curl -fL --retry 8 --retry-all-errors "$BASE_URL" | tar xz -C "$TREE" --strip-components=1
}

configure() {
	make -C "$TREE" O= defconfig >/dev/null
	# Built-in (not =m): there is no module loading in the first boot.
	cat >> "$TREE/.config" <<"FRAG"
CONFIG_DRM=y
CONFIG_DRM_MSM=y
CONFIG_DRM_SIMPLEDRM=y
CONFIG_DRM_FBDEV_EMULATION=y
CONFIG_FRAMEBUFFER_CONSOLE=y
CONFIG_QCOM_SCM=y
CONFIG_ARM_SMMU=y
CONFIG_PINCTRL_SM8350=y
CONFIG_QCOM_CLK_RPMH=y
CONFIG_QCOM_RPMH=y
CONFIG_I2C_GPIO=y
CONFIG_INPUT_EVDEV=y
CONFIG_USB_GADGET=y
CONFIG_USB_DWC3=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_F_FS=y
CONFIG_USB_CONFIGFS_ECM=y
CONFIG_USB_CONFIGFS_RNDIS=y
CONFIG_BLK_DEV_INITRD=y
CONFIG_DEVTMPFS=y
CONFIG_DEVTMPFS_MOUNT=y
CONFIG_DEBUG_INFO_NONE=y
CONFIG_MODULE_SIG=n
CONFIG_SYSTEM_TRUSTED_KEYS=""
FRAG
	make -C "$TREE" olddefconfig >/dev/null
}

# The debug console. There is no UART on this phone and no DSI panel driver in mainline, so the
# observable channel is a USB CDC-ACM gadget: the phone appears as a serial port on the host and
# dumps dmesg once the gadget binds. tty0 is still requested for the UEFI/simpledrm path.
initramfs() {
	local rd=$OUT/initrd
	rm -rf "$rd"; mkdir -p "$rd"
	curl -fL --retry 5 -o "$OUT/alpine.tar.gz" \
		"https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-minirootfs-3.20.3-aarch64.tar.gz"
	tar xzf "$OUT/alpine.tar.gz" -C "$rd"
	cat > "$rd/init" <<"INIT"
#!/bin/sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts 2>/dev/null
G=/sys/kernel/config/usb_gadget/g1
mkdir -p $G 2>/dev/null
echo 0x1d6b > $G/idVendor
echo 0x0104 > $G/idProduct
mkdir -p $G/strings/0x409 $G/configs/c.1/strings/0x409
echo LEMONADEP0001 > $G/strings/0x409/serialnumber
echo OnePlus > $G/strings/0x409/manufacturer
echo "Lemonadep Debug Console" > $G/strings/0x409/product
echo acm > $G/configs/c.1/strings/0x409/configuration
mkdir -p $G/functions/acm.usb0
ln -sf $G/functions/acm.usb0 $G/configs/c.1/acm.usb0 2>/dev/null
UDC=$(ls /sys/class/udc 2>/dev/null | head -1)
[ -n "$UDC" ] && echo $UDC > $G/UDC
sleep 2
{
  echo "===== LEMONADEP INITRAMFS UP (gadget: ${UDC:-none}) ====="
  uname -a
  dmesg | tail -80
} > /dev/ttyGS0 2>/dev/null
while true; do setsid /sbin/getty -L 115200 ttyGS0 vt100 2>/dev/null || sleep 5; done
INIT
	chmod +x "$rd/init"
	echo "root:x:0:0:root:/root:/bin/sh" > "$rd/etc/passwd"
	echo "root:x:0:" > "$rd/etc/group"
	( cd "$rd" && find . | cpio -o -H newc 2>/dev/null | gzip -9 ) > "$OUT/initramfs.cpio.gz"
}

main() {
	host_deps
	fetch_tree
	configure
	make -C "$TREE" -j"$JOBS" Image.gz
	make -C "$TREE" -j"$JOBS" qcom/sm8350-oneplus-lemonadep.dtb
	mkdir -p "$OUT"
	cp "$TREE/arch/arm64/boot/Image.gz" "$OUT/"
	cp "$TREE/arch/arm64/boot/dts/qcom/sm8350-oneplus-lemonadep.dtb" "$OUT/"
	initramfs
	RAMDISK=$OUT/initramfs.cpio.gz \
	CMDLINE="console=ttyGS0 console=tty0 earlycon loglevel=8 ignore_loglevel" \
		bash "$(dirname "$0")/../boot/pack-bootimg.sh" \
			"$OUT/Image.gz" "$OUT/sm8350-oneplus-lemonadep.dtb" "$OUT/boot.img"
	ls -lh "$OUT"/Image.gz "$OUT"/sm8350-oneplus-lemonadep.dtb "$OUT"/initramfs.cpio.gz "$OUT"/boot.img
}

main "$@"
