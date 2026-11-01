#!/usr/bin/env python3
"""Log every GPU address the driver hands out and takes back, to explain an SMMU fault.

The first hakios-metal draw on lemonadep (2026-11-01, `metal3.log`) hung, and the kernel's
report was:

    adreno: 0: THE SMMU REFUSED the 3D core: status 0x80000402, address 0x23760040, syndrome 0xb0013

status bit 1 is the SMMU's TF (translation fault, drivers/iommu/arm/arm-smmu/arm-smmu.h), so
0x23760000 was in no mapping at all when the GPU touched it: not a permission problem, a hole.
Either a buffer was freed while a command buffer still named it, or an address was computed
wrongly. With `gpu_log=2` the log then says which: every range given and given back, in order,
with the buffer's handle and flags for the ones a client made.

    gpu_log=2 ... (boot-arg; gpu_log=1 already prints a line per submission)

Patched in two files because a working tree has the source twice: `xnu/files/` is what
`xnu/apply.sh` copies in, and `xnu-src/xnu-8796.121.2/` is the copy the build reads.
Idempotent: a second run says so and exits 0.
"""

import io
import os
import sys

MARKER = "given back (%llu bytes)"

# --- bsd/dev/redwood_adreno.c: the one allocator every client goes through --------------------

ALLOC_OLD = """			gpu_va_used += size;
			gpu_va_live++;
			return address;"""

ALLOC_NEW = """			gpu_va_used += size;
			gpu_va_live++;
			if (gpu_log >= 2) {
				printf("adreno: address %#llx..%#llx given (%llu bytes)\\n", address, address + size - 1, size);
			}
			return address;"""

FREE_OLD = """	size = gpu_address_span(size);
	gpu_va_used -= size;
	gpu_va_live--;"""

FREE_NEW = """	size = gpu_address_span(size);
	gpu_va_used -= size;
	gpu_va_live--;
	if (gpu_log >= 2) {
		printf("adreno: address %#llx..%#llx given back (%llu bytes)\\n", address, address + size - 1, size);
	}"""

# --- iokit/Kernel/RedwoodGPU.cpp: the same ranges with the client's handle and flags ----------

BUFFER_OLD = """	b->size = size;
	b->flags = flags;
	b->seed = 0;"""

BUFFER_NEW = """	b->size = size;
	b->flags = flags;
	if (gpu_log >= 2) {
		IOLog("RedwoodGPU: buffer %u: %#llx..%#llx (%llu bytes, flags %#x)\\n", *handle, b->address,
		    b->address + b->size - 1, b->size, b->flags);
	}
	b->seed = 0;"""

ADRENO = os.path.join("bsd", "dev", "redwood_adreno.c")
GPU = os.path.join("iokit", "Kernel", "RedwoodGPU.cpp")


def patch(path, pairs, marker):
    src = io.open(path, encoding="utf-8").read()
    if marker in src:
        print("gpu-address-log: %s is already patched" % path)
        return True
    for old, new in pairs:
        if old not in src:
            print("gpu-address-log: %s does not have the expected text (another kernel?)" % path)
            return False
        src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("gpu-address-log: patched %s" % path)
    return True


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser("~/fkernel")
    trees = [os.path.join(root, "xnu", "files"),
             os.path.join(root, "xnu-src", "xnu-8796.121.2")]
    seen = 0
    ok = True
    for tree in trees:
        for rel, pairs, marker in ((ADRENO, [(ALLOC_OLD, ALLOC_NEW), (FREE_OLD, FREE_NEW)], MARKER),
                                   (GPU, [(BUFFER_OLD, BUFFER_NEW)], MARKER)):
            path = os.path.join(tree, rel)
            if not os.path.isfile(path):
                continue
            seen += 1
            ok = patch(path, pairs, marker) and ok
    if not seen:
        sys.exit("gpu-address-log: neither tree is under %s" % root)
    print('gpu-address-log: rebuild with: SKIP="loader images boot" common/build.sh <device>, '
          'and boot with gpu_log=2')
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
