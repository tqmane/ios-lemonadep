#!/usr/bin/env python3
"""Give a long job list room in the head of the kernel log.

The kernel hands its console log back to the loader, and the loader keeps two pieces of it:
the **first 256 KB** as it is, then a **1 MB ring** of the most recent part. Everything between
is dropped, and the log says so where it happened:

    [... the log between the first 256 KB and the last 1 MB was dropped ...]

That is fine for a boot where the interesting thing is at the end, and wrong for a job list whose
output is at the beginning. It cost us the first `hakios-metal-probe` run (2026-11-01, `metal1.log`):
`com.redwood.demo` starts at byte 164,093 of the log, so only ~92 KB of head was left, `metal_test`
used all of it, and the probe's report -- the whole reason for the boot -- went into the hole. The
probe had run; the `$` line for it was gone too.

The change, in `osfmk/arm64/loader_return.c`:

    LOADER_LOG_SIZE  1536 KB -> 2048 KB
    LOADER_LOG_HEAD   256 KB -> 1024 KB
    LOADER_LOG_RING  1024 KB ->  768 KB

Head + ring is 1792 KB on purpose: the loader composes the log into a 2 MB `out_buf` together with
its own log and two separators, and `compose_logs()` truncates silently if that does not fit. This
way nothing is truncated and the head holds a job list's whole report. The buffer is BSS, so the
kernel file stays the same size.

The file exists twice in a working tree -- `xnu/files/` is the source `xnu/apply.sh` copies in, and
`xnu-src/xnu-8796.121.2/` is where it was copied to. `apply.sh` refuses a tree that already exists,
so both are patched here. Rebuild the kernel only:

    SKIP="loader images boot" common/build.sh lemonadep

Idempotent: a second run says so and exits 0.
"""

import io
import os
import sys

OLD = """#define LOADER_LOG_SIZE (1536 * 1024)
#define LOADER_LOG_HEAD (256 * 1024)
#define LOADER_LOG_RING (1024 * 1024)"""

NEW = """#define LOADER_LOG_SIZE (2048 * 1024)
#define LOADER_LOG_HEAD (1024 * 1024)
#define LOADER_LOG_RING (768 * 1024)"""

OLD_NOTE = "[... the log between the first 256 KB and the last 1 MB was dropped ...]"
NEW_NOTE = "[... the log between the first 1 MB and the last 768 KB was dropped ...]"

MARKER = "LOADER_LOG_HEAD (1024 * 1024)"

# xnu/files/ is the source; xnu-src/ is the copy apply.sh made, which the build reads
REL = os.path.join("osfmk", "arm64", "loader_return.c")
COPIES = [os.path.join("xnu", "files", REL),
          os.path.join("xnu-src", "xnu-8796.121.2", REL)]


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser("~/fkernel")
    seen = 0

    for rel in COPIES:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            continue
        seen += 1
        src = io.open(path, encoding="utf-8").read()
        if MARKER in src:
            print("log-head: %s is already patched" % path)
            continue
        if OLD not in src:
            sys.exit("log-head: the LOADER_LOG_* defines are not the expected ones in %s "
                     "(another kernel?)" % path)
        src = src.replace(OLD, NEW, 1)
        if OLD_NOTE in src:
            src = src.replace(OLD_NOTE, NEW_NOTE, 1)
        io.open(path, "w", encoding="utf-8", newline="\n").write(src)
        print("log-head: patched %s" % path)

    if not seen:
        sys.exit("log-head: no %s under %s" % (REL, root))
    print('log-head: rebuild with: SKIP="loader images boot" common/build.sh <device>')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
