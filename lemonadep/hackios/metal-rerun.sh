#!/bin/bash
# Re-run on the loader that is already up and already holds the 2.4 GB system image: wait for the
# current run to end, stage the new payload, run it, capture the log. Status lines go to
# metal-rerun.status so the caller never has to block on it.
#
# usage: bash metal-rerun.sh [LOGNAME] [CAPTURE_SECONDS]
set -u
DIR="/d/ios port/ios-sweet/lemonadep/out/hackios"
LOG=${1:-metal18.log}
CAP=${2:-65}
FB=/c/Users/Luka/AppData/Local/Android/Sdk/platform-tools/fastboot.exe
ST="$DIR/metal-rerun.status"
cd "$DIR" || exit 1

say() { echo "$(date +%H:%M:%S) $*" >> "$ST"; }

say "waiting for the running kernel to hand back"
for i in $(seq 1 100); do
	r=$(timeout 8 "$FB" getvar result 2>&1 | head -1 | tr -d '\r')
	case "$r" in *running*) sleep 4;; *) say "run over: $r"; break;; esac
done

p=$(timeout 8 "$FB" getvar product 2>&1 | head -1 | tr -d '\r')
case "$p" in
	*xnuloader*) ;;
	*) say "loader is gone ($p): the resident system image went with it"; exit 2;;
esac

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
say "done"
