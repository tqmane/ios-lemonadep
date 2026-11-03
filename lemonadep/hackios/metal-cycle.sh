#!/bin/bash
# One full graphics cycle on the phone, unattended, ending with the phone back in iOS.
#
#   bash metal-cycle.sh [LOGNAME] [CAPTURE_SECONDS]
#
# From whatever state the phone is in it: brings it to the bootloader (from iOS nothing can be sent,
# so iOS is left alone and the script says so), boots the XNU loader, stages the 2.4 GB system image
# and the payload, runs the kernel, captures the log, and then reboots the phone so it starts the
# standalone iOS image on boot_b again. Every step is one line in metal-cycle.status.
set -u
DIR="/d/ios port/ios-sweet/lemonadep/out/hackios"
LOG=${1:-metal20.log}
CAP=${2:-70}
FB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/fastboot.exe
ADB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/adb.exe
ST="$DIR/metal-cycle.status"
cd "$DIR" || exit 1

say() { echo "$(date +%H:%M:%S) $*" >> "$ST"; }
state() { timeout 8 "$FB" getvar product 2>&1 | head -1 | tr -d '\r'; }

say "cycle start: log=$LOG capture=${CAP}s"
p=$(state)
say "phone: $p"

case "$p" in
	*xnuloader*) say "the XNU loader is already up";;
	*lahaina*)   say "booting the loader image"
	             timeout 90 "$FB" boot lemonadep-boot.img >/dev/null 2>&1
	             for i in $(seq 1 15); do p=$(state); case "$p" in *xnuloader*) break;; esac; sleep 4; done
	             case "$p" in *xnuloader*) say "loader is up";; *) say "the loader did not come up ($p)"; exit 1;; esac;;
	*)
		# iOS: it has no fastboot, and nothing sent to it is answered. Say so instead of hanging.
		say "the phone is not in the bootloader ($p): hold Power + Volume Down to get there"
		exit 2;;
esac

timeout 60 "$FB" oem ramdisk >/dev/null 2>&1
say "staging the system image (87 s)"
if ! timeout 280 "$FB" stage system.apfs >/dev/null 2>&1; then
	say "the system image did not stage: the loader went away"
	exit 3
fi
say "staging the payload"
timeout 120 "$FB" stage run-payload.bin >/dev/null 2>&1
timeout 20 "$FB" oem run >/dev/null 2>&1
say "run started, capturing at +${CAP}s"

sleep "$CAP"
timeout 20 "$FB" oem log >/dev/null 2>&1
timeout 90 "$FB" get_staged "$LOG.raw" >/dev/null 2>&1
if [ -s "$LOG.raw" ]; then
	python3 - "$LOG.raw" "$LOG" <<'EOF'
import sys
d = open(sys.argv[1], 'rb').read().rstrip(b'\x00')
open(sys.argv[2], 'w', encoding='utf-8', errors='replace').write(d.decode('utf-8', 'replace'))
EOF
	say "log: $LOG ($(wc -c < "$LOG") bytes)"
else
	say "the log fetch came back empty"
fi

# hand the phone back: boot_b holds the standalone iOS image, so this starts iOS by itself
say "rebooting into iOS (boot_b)"
timeout 25 "$FB" reboot >/dev/null 2>&1
say "cycle done"
