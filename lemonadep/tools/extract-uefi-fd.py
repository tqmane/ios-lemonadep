#!/usr/bin/env python3
"""Take the UEFI FD out of a boot image, so the chain that booted can be rebuilt.

`mkxnuimg.py` writes `gzip(BootShim.bin + SILICIUM_UEFI.fd + payload) + dtb`
(see the module docstring there). The FD is therefore in the image, whole, and
an image that reached the screen carries the exact FD that reached it. That is
worth more than a fresh build of the UEFI: the local Mu-Silicium tree has
uncommitted platform edits, and a rebuild produces a different FD, not the one
the phone ran.

This is how lemonadep's FD was recovered on 2026-11-01, after the directory the
device profile pointed at (`/root/hakios/fz/Mu-Silicium`) went away with a
re-clone of hakios. The copy that came out has FD_BASE 0x9FD00000, as
`Resources/Configs/lemonadep.toml` asks for; the copy left in
`Mu-Silicium/Build/` is a 0x9BE00000 build and would not run where the shim
loads it.

    python3 lemonadep/tools/extract-uefi-fd.py out/lemonadep-boot.img /root/lemonadep-uefi/SILICIUM_UEFI.fd

The FD is found by its FV header signature (`_FVH` at 0x28 of the FV), not by a
fixed offset. The FV header carries no load address (the FV is position
independent; the base is where the shim copies it), so pass the profile's
`FD_BASE` as an optional third argument and the script asserts the FD really
was built for that base -- it appears as a constant in the image, twice: in the
DxeCore's PCDs and in the memory-map description.
"""

import hashlib
import io
import os
import struct
import sys
import zlib

FVH_OFFSET = 0x28          # the FV header signature sits here in an FV
FVH = b"_FVH"


def find_fv(blob):
    """(offset, attributes, size) of the first FV in the blob, or None."""
    start = 0
    while True:
        p = blob.find(FVH, start)
        if p < 0:
            return None
        fv = p - FVH_OFFSET
        if fv >= 0:
            # EFI_FIRMWARE_VOLUME_HEADER: FvLength is a uint64 at 0x20,
            # Attributes a uint32 at 0x30 (there is no base field)
            length = struct.unpack_from("<Q", blob, fv + 0x20)[0]
            attrs = struct.unpack_from("<I", blob, fv + 0x30)[0]
            if 0 < length <= len(blob) - fv:
                return fv, attrs, length
        start = p + 1


def main(argv):
    if len(argv) not in (3, 4):
        sys.exit("usage: extract-uefi-fd.py BOOT.IMG OUT.fd [FD_BASE]")
    img_path, out_path = argv[1], argv[2]
    want_base = int(argv[3], 0) if len(argv) == 4 else None
    img = io.open(img_path, "rb").read()

    # the compressed part starts at the first gzip member (the boot header is
    # before it; the dtb, if any, is after it and is not gzipped)
    gz = img.find(b"\x1f\x8b\x08")
    if gz < 0:
        sys.exit("extract-uefi-fd: no gzip member in %s" % img_path)
    # zlib, not gzip.decompress: the dtb follows the gzip member uncompressed,
    # and gzip.decompress treats that trailing data as a broken second member
    try:
        d = zlib.decompressobj(31)
        blob = d.decompress(img[gz:]) + d.flush()
    except Exception as e:  # a truncated image
        sys.exit("extract-uefi-fd: %s does not decompress: %s" % (img_path, e))

    found = find_fv(blob)
    if not found:
        sys.exit("extract-uefi-fd: no FV header in the payload of %s" % img_path)
    fv, attrs, length = found
    # the FD is the whole flash device the FV sits in, and is what mkxnuimg
    # asserted was FD_SIZE bytes (0x200000 for lemonadep): round up from the FV
    size = 1 << (length - 1).bit_length() if length & (length - 1) else length
    size = max(size, 0x200000) if length <= 0x200000 else size
    if fv + size > len(blob):
        size = len(blob) - fv
    fd = blob[fv:fv + size]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    io.open(out_path, "wb").write(fd)
    print("extract-uefi-fd: %s -> %s" % (img_path, out_path))
    print("  %d bytes, FV at payload+0x%x, length 0x%x, attributes 0x%x, sha256 %s" %
          (len(fd), fv, length, attrs, hashlib.sha256(fd).hexdigest()[:16]))
    if want_base is not None:
        where = []
        pat = struct.pack("<Q", want_base)
        i = fd.find(pat)
        while i >= 0:
            where.append(i)
            i = fd.find(pat, i + 1)
        if not where:
            sys.exit("extract-uefi-fd: FD_BASE 0x%x does not appear in %s: this FD "
                     "was built for another base" % (want_base, out_path))
        print("  FD_BASE 0x%x found at %s" % (want_base, ", ".join("0x%x" % w for w in where)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
