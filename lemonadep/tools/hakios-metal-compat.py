#!/usr/bin/env python3
"""Make oosexgang's Metal driver (hakios-metal) build and run on lemonadep.

Two changes, both idempotent, both needed before `make ios MESA=1 HAKIOS=<tree>`:

1. include/hakios-metal/a6xx.hpp -- `constexpr fui()` took the sign bit with
   `__builtin_signbit`, which clang 18 refuses in a constant expression
   ("not a constant expression"), so the library did not build at all. The
   replacement, `__builtin_bit_cast(uint32_t, f) & 0x80000000u`, is the same
   value (verified: -0.0f -> 0x80000000, NaN -> 0x7fc00000) and is constexpr in
   both C++17 and C++20. Worth reporting upstream: it is a portability bug, not
   a difference of this port.

2. src/iokit_transport.cpp -- the transport opens the kernel's GPU user client
   by service name. Ours is `RedwoodGPU` (xnu/files/iokit/Kernel/RedwoodGPU.cpp,
   setName("RedwoodGPU")); hakios's is `HakiosGPU`. The request numbers and the
   structures are identical, so this is the whole of the kernel-side difference
   (verified 2026-11-01).

Run it on the hakios-metal checkout before building:

    python3 lemonadep/tools/hakios-metal-compat.py ~/hakios-metal
    make -C ~/hakios-metal ios MESA=1 HAKIOS=~/fkernel

A second run says what is already done and changes nothing.
"""

import io
import os
import sys

A6XX_OLD = "    uint32_t sign = __builtin_signbit(f) ? 0x80000000u : 0u;"
A6XX_NEW = "    uint32_t sign = __builtin_bit_cast(uint32_t, f) & 0x80000000u;"

TRANSPORT_OLD = [
    ('IOServiceMatching("HakiosGPU")', 'IOServiceMatching("RedwoodGPU")'),
    ('"no HakiosGPU service: the kernel has not started the GPU (gpu=1, the firmware in fw-gpu/, the phone)"',
     '"no RedwoodGPU service: the kernel has not started the GPU (gpu=1, the firmware in fw-gpu/, the phone)"'),
    ('*why = "HakiosGPU would not open: error "', '*why = "RedwoodGPU would not open: error "'),
    ("// The kernel's GPU driver (HakiosGPU)",
     "// The kernel's GPU driver (RedwoodGPU on lemonadep, HakiosGPU on hakios)"),
]


def patch(path, pairs, what):
    src = io.open(path, encoding="utf-8").read()
    if all(new in src for _, new in pairs):
        print("hakios-metal-compat: %s is already patched" % path)
        return False
    for old, new in pairs:
        if old not in src:
            if new in src:
                continue
            sys.exit("hakios-metal-compat: %s: %s not found in %s (moved upstream?)"
                     % (what, old, path))
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("hakios-metal-compat: patched %s" % path)
    return True


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser("~/hakios-metal")
    a6xx = os.path.join(root, "include", "hakios-metal", "a6xx.hpp")
    transport = os.path.join(root, "src", "iokit_transport.cpp")
    for path in (a6xx, transport):
        if not os.path.isfile(path):
            sys.exit("hakios-metal-compat: no %s (is %s a hakios-metal checkout?)" % (path, root))

    changed = patch(a6xx, [(A6XX_OLD, A6XX_NEW)], "constexpr fui()")
    changed |= patch(transport, TRANSPORT_OLD, "the GPU service name")
    if changed:
        print("hakios-metal-compat: now build it: make -C %s ios MESA=1 HAKIOS=<tree>" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
