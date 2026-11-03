#!/bin/bash
# Repack ONLY run-payload.bin from the current tree + common/devices/lemonadep.conf's boot-args.
#
# Why: build-boot.sh also rebuilds the UEFI boot image, which needs the Mu-Silicium FD + DTB at a
# fixed path. The boot image itself does not change between graphics experiments -- only the kernel
# cmdline does -- so this repacks the payload alone and leaves lemonadep-boot.img untouched.
#
# usage (from WSL): SECS=200 bash repack-payload.sh
set -e
FK=${FK:-/root/fkernel}
SECS=${SECS:-200}
OUT=${OUT:-"/mnt/d/ios port/ios-sweet/lemonadep/out/hackios"}
cd "$FK"

DEVICE=lemonadep
. common/devices/lemonadep.conf
[ -n "${ARGS:-}" ] && BOOTARGS=$ARGS     # ARGS="...": the whole list instead of the profile's
for w in ${DROP:-}; do BOOTARGS=$(echo " $BOOTARGS " | sed "s/ $w / /g; s/^ //; s/ $//"); done

# en0's address is made at kernel start, before configd (see build-standalone.sh); kept out of git
case " $BOOTARGS " in
*" wlan_ath=1 "*)
	MACF=$FK/fw-wlan/mac
	[ -s "$MACF" ] || od -An -N5 -tx1 /dev/urandom | awk '{printf "02:%s:%s:%s:%s:%s\n", $1, $2, $3, $4, $5}' > "$MACF"
	BOOTARGS="$BOOTARGS wifi_mac=$(cat "$MACF")";;
esac

K=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
[ -f "$K" ] || { echo "no kernel at $K (build it with common/build.sh)"; exit 1; }
[ -f userland/root.apfs ] || { echo "no userland/root.apfs"; exit 1; }

python3 xnuloader/mkpayload.py -o run-payload.bin kernel="$K" ramdisk=userland/root.apfs \
	--cmdline "loader_return_after=$SECS epoch=$(date +%s) sb_delay=8 $BOOTARGS ${EXTRA:-}"
mkdir -p "$OUT"
cp run-payload.bin "$OUT/run-payload.bin"
echo "payload: $(stat -c %s run-payload.bin) bytes, loader_return_after=$SECS"
echo "cmdline: $BOOTARGS ${EXTRA:-}"
