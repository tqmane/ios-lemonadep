#!/bin/bash
# One hands-free Metal test iteration. Never flashes, never cold-resets.
#
#   bash usb-test.sh LOGNAME [SECS]
#
# From the bootloader it boots the XNU loader over USB and keeps it there for the whole session:
# stage the 2.4 GB system image once per loader boot, stage the payload, run the kernel bounded by
# loader_return_after (SECS in the payload), fetch the log live at intervals and whole at the end.
# The loader stays in its USB command loop afterwards, so the next iteration is just: stage the new
# payload and run again. No hands, no flashing, no touched phone.
#
# Every step is one line in usb-test.status. Every fastboot call is bounded, so no step can hang
# the caller: the script itself runs in the background and is polled.
set -u
DIR="/d/ios port/ios-sweet/lemonadep/out/hackios"
LOG=${1:?usage: usb-test.sh LOGNAME [SECS]}
CAP=${2:-150}
FB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/fastboot.exe
ST="$DIR/usb-test.status"
cd "$DIR" || exit 1

say() { echo "$(date +%H:%M:%S) $*" >> "$ST"; }
state() { timeout 8 "$FB" getvar product 2>&1 | head -1 | tr -d '\r'; }

say "usb-test: log=$LOG capture~${CAP}s"
p=$(state)
say "phone: $p"

 LOADER_UP=0
case "$p" in
	*xnuloader*) say "loader already up, keeping the session (system image stays staged)"; LOADER_UP=1;;
	*lahaina*)
		say "booting the loader image over USB"
		if ! timeout 90 "$FB" boot lemonadep-boot.img >/dev/null 2>&1; then say "boot command failed"; exit 1; fi
		for i in $(seq 1 15); do p=$(state); case "$p" in *xnuloader*) break;; esac; sleep 4; done
		case "$p" in *xnuloader*) say "loader is up";; *) say "loader did not come up ($p)"; exit 1;; esac;;
	*) say "phone is neither in the bootloader nor in the loader ($p): cannot proceed hands-free"; exit 2;;
esac

if [ "$LOADER_UP" = 0 ]; then
	timeout 60 "$FB" oem ramdisk >/dev/null 2>&1
	say "staging the system image (~90 s)"
	if ! timeout 280 "$FB" stage system.apfs >/dev/null 2>&1; then say "system image did not stage"; exit 3; fi
fi
say "staging the payload"
if ! timeout 120 "$FB" stage run-payload.bin >/dev/null 2>&1; then say "payload did not stage"; exit 4; fi
if ! timeout 20 "$FB" oem run >/dev/null 2>&1; then say "run did not start"; exit 5; fi
say "run started, fetching live log at +60 s and +120 s"
sleep 60
timeout 30 "$FB" oem log >/dev/null 2>&1
timeout 60 "$FB" get_staged "$LOG.live1.raw" >/dev/null 2>&1
say "live1: $(wc -c < "$LOG.live1.raw" 2>/dev/null || echo 0) bytes"
sleep 60
timeout 30 "$FB" oem log >/dev/null 2>&1
timeout 60 "$FB" get_staged "$LOG.live2.raw" >/dev/null 2>&1
say "live2: $(wc -c < "$LOG.live2.raw" 2>/dev/null || echo 0) bytes"

# the run ends by itself at loader_return_after; wait for the loader to answer again, then fetch all
say "waiting for the run to end (loader answers again)"
for i in $(seq 1 20); do
	if timeout 20 "$FB" getvar result >/dev/null 2>&1; then break; fi
	sleep 10
done
timeout 30 "$FB" oem log >/dev/null 2>&1
timeout 90 "$FB" get_staged "$LOG.raw" >/dev/null 2>&1
if [ -s "$LOG.raw" ]; then
	python3 - "$LOG.raw" "$LOG" <<'EOF'
import sys
d = open(sys.argv[1], 'rb').read().rstrip(b'\x00')
open(sys.argv[2], 'w', encoding='utf-8', errors='replace').write(d.decode('utf-8', 'replace'))
EOF
	say "log: $LOG ($(wc -c < "$LOG") bytes); loader still up, session kept"
else
	say "final log fetch came back empty (live captures above still stand)"
fi
say "usb-test done"
