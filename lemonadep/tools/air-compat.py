#!/usr/bin/env python3
"""Add the fields hakios-metal's compiler reads to our AIR front end's header.

Why. oosexgang's Metal driver (github.com/oosexgang/hakios-metal) compiles Apple's
shaders on the phone through Mesa's AIR front end, and its compiler.cpp reads seven
fields of `nir_air.h` that our tree's front end (furangelz's, which came with
xnu-deps) does not have:

    air_resource.null_texture            Metal's null texture slot
    air_resource.argbuf_offset           an argument-buffer member's offset
    air_resource.ir_write                written by an instruction, not just the API
    air_shader_info.has_threadgroup_arg  a [[threadgroup]] argument
    air_shader_info.threadgroup_arg_base its base
    air_to_nir_options.interface_only    link a stage's interface only
    air_constant_value.supplied          "given as zero" vs "not given"

This front end is not the one hakios-metal was written against (that one lives in
vcvkk/darwin-redwood and is not published), and it is richer in other ways
(raster-order groups, decoded samplers, vertex attributes, framebuffer-fetch
targets). The seven fields are added as always-zero: the structs are filled with
compound literals and rzalloc, so a field nobody sets reads as false/0.

What that costs, until the front end grows them:
  * argument-buffer members bind at offset 0 (Metal argument buffers misbehave);
  * Metal's null texture reads whatever the application bound there;
  * [[threadgroup]] arguments and interface-only linking are not served;
  * a function constant supplied as zero is indistinguishable from one not supplied.

Run it after `xnu-deps/setup.sh` (and after any Mesa re-extract), then rebuild the
iOS AIR archive:

    python3 lemonadep/tools/air-compat.py ~/fkernel/xnu-deps/build/mesa/mesa-25.0.7
    ninja -C ~/fkernel/xnu-deps/build/mesa/build-softpipe-freedreno \\
        src/compiler/air/libair.a

The script is idempotent: it says so and exits 0 when the fields are already there.
"""

import io
import os
import sys

RESOURCE_TAIL = "   unsigned argbuf_set;\n   unsigned argbuf_id;\n};"
RESOURCE_NEW = (
    "   unsigned argbuf_set;\n   unsigned argbuf_id;\n\n"
    "   /* hakios-metal's compiler reads these three; this front end does not\n"
    "    * produce them yet, so they are always false/0. See air-compat.py. */\n"
    "   bool null_texture;\n   unsigned argbuf_offset;\n"
    "   bool ir_write;      /* written by an instruction (not just the API) */\n};"
)

INFO_TAIL = "   unsigned threadgroup_bytes; /* static threadgroup memory */\n};"
INFO_NEW = (
    "   unsigned threadgroup_bytes; /* static threadgroup memory */\n\n"
    "   /* hakios-metal's compiler reads these; this front end does not produce\n"
    "    * them yet (always false/0). See air-compat.py. */\n"
    "   bool has_threadgroup_arg;\n   unsigned threadgroup_arg_base;\n};"
)

OPTIONS_TAIL = "   bool library_wrapper;\n};"
OPTIONS_NEW = (
    "   bool library_wrapper;\n\n"
    "   /* hakios-metal sets this when it links stages; this front end has no such\n"
    "    * mode and ignores it. See air-compat.py. */\n"
    "   bool interface_only;\n};"
)

CONSTANT_TAIL = (
    "struct air_constant_value {\n"
    "   unsigned index;     /* the function constant's index */\n"
    "   uint64_t bits;      /* its value, as the bits of its type */\n"
    "};"
)
CONSTANT_NEW = (
    "struct air_constant_value {\n"
    "   unsigned index;     /* the function constant's index */\n"
    "   uint64_t bits;      /* its value, as the bits of its type */\n"
    "   /* hakios-metal's compiler sets this to tell \"given as zero\" from \"not\n"
    "    * given\"; this front end has no such distinction yet. See air-compat.py. */\n"
    "   bool supplied;\n};"
)


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser(
        "~/fkernel/xnu-deps/build/mesa/mesa-25.0.7")
    path = os.path.join(root, "src", "compiler", "air", "nir_air.h")
    if not os.path.isfile(path):
        sys.exit("air-compat: no %s" % path)

    src = io.open(path, encoding="utf-8").read()
    if "null_texture" in src:
        print("air-compat: %s is already patched" % path)
        return 0

    for old, new, what in ((RESOURCE_TAIL, RESOURCE_NEW, "air_resource"),
                           (INFO_TAIL, INFO_NEW, "air_shader_info"),
                           (OPTIONS_TAIL, OPTIONS_NEW, "air_to_nir_options"),
                           (CONSTANT_TAIL, CONSTANT_NEW, "air_constant_value")):
        if old not in src:
            sys.exit("air-compat: %s not found in %s (another front end?)" % (what, path))
        src = src.replace(old, new, 1)

    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("air-compat: patched %s" % path)
    print("air-compat: rebuild the iOS archive: ninja -C <build-softpipe-freedreno> "
          "src/compiler/air/libair.a")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
