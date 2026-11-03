#!/bin/bash
# One unattended metal run: wait for the bootloader, boot the loader, stage the system image and the
# payload, run, then fetch the log. Prints one short status line per step to metal-run.status so the
# caller can poll it without blocking on the 87 s staging or the run itself.
#
# usage: bash metal-run.sh [LOGNAME] [CAPTURE_SECONDS]
set -u
DIR="/d/ios port/ios-sweet/lemonadep/out/hackios"
LOG=${1:-metal17.log}
CAP=${2:-70}
FB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/fastboot.exe
ADB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/adb.exe
ST="$DIR/metal-run.status"
cd "$DIR" || exit 1

say() { echo "$(date +%H:%M:%S) $*" >> "$ST"; }

say "waiting for the bootloader (hold Power + Volume Down)"
ok=0
for i in $(seq 1 120); do
	p=$(timeout 8 "$FB" getvar product 2>&1 | head -1 | tr -d '\r')
	case "$p" in *lahaina*) ok=1; say "bootloader is up"; break;; esac
	s=$("$ADB" devices 2>&1 | sed -n '2p')
	if [ -n "$s" ]; then timeout 15 "$ADB" reboot bootloader >/dev/null 2>&1; fi
	sleep 5
done
[ "$ok" = 1 ] || { say "no bootloader after 10 min, giving up"; exit 1; }

timeout 90 "$FB" boot lemonadep-boot.img >/dev/null 2>&1
for i in $(seq 1 15); do
	p=$(timeout 8 "$FB" getvar product 2>&1 | head -1 | tr -d '\r')
	case "$p" in *xnuloader*) say "loader is up"; break;; esac
	sleep 4
done

timeout 60 "$FB" oem ramdisk >/dev/null 2>&1
say "staging the system image (87 s)"
timeout 280 "$FB" stage system.apfs >/dev/null 2>&1
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
	say "log fetch came back empty"
fi
timeout 15 "$FB" getvar result 2>&1 | head -1 >> "$ST"
say "done"
