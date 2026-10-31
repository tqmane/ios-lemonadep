#!/usr/bin/env python3
"""Type an AIR image write by the value it stores, not by the call's return type.

Why. `air.write_texture_2d` (and the `read_write` forms) return `void`, and our AIR
front end typed the `nir_image_store` it emits by that return type -- so every half
or float image write became a `uint` store. ir3 emits `stib.b.typed.u32` for a uint
store and a typed store converts its source as its type says, so a kernel declared
`texture2d<half, write>` had its values converted as integers. vcvkk's front end
fixed exactly this on 29 October (see hakios-metal's compiler.cpp, the sentence
"they did not for every half or float image until 29 October"), and its fix is what
this reproduces: the store's `src_type` is taken from the stored value's own AIR
type, while the signedness of an integer store still comes from the intrinsic's name
(`.s`/`.u`), as before.

Measured cost of not having it (host sweep over the iOS 16.5 image, 2026-11-01):
1,975 of the 3,128 kernels refused, by far the largest single cause:
    1203 x texture2d<float, write> ... move uint values through it
     743 x texture2d<half, write>  ... move uint values through it
      29 x texture2d_array<half, write> ...
and in CoreAnimation's own default.metallib the two `inplace_copy` fragments.

Nothing of ours reads the store's src_type as a claim about the texture's class:
air_metal.c's slot_shapes() takes the element type from tex instructions only, and
says so in a comment.

Run it after `xnu-deps/setup.sh` (and after any Mesa re-extract), then rebuild the
AIR archive for both builds:

    python3 lemonadep/tools/air-store-type.py ~/fkernel/xnu-deps/build/mesa/mesa-25.0.7
    ninja -C ~/fkernel/xnu-deps/build/mesa/build-softpipe-freedreno \\
        src/compiler/air/libair.a
    ninja -C /root/mesa-host-build src/compiler/air/libair.a

The script is idempotent: it says so and exits 0 when the change is already there.
"""

import io
import os
import sys

OLD = """      nir_def *value = air_get_ssa(c, in->operands[arg++]);
      if (!value)
         return false;
"""

NEW = """      /* The store's type is the VALUE's, not the call's return type: air.write_texture_*
       * returns void, so typing by the call made every half or float image write a uint
       * store, and ir3's stib.b.typed then converts the value as the wrong type says.
       * (vcvkk's front end made the same change on 29 October; air_metal.c's slot_shapes
       * takes a slot's element type from tex instructions only, so nothing here reads
       * src_type as a claim about the texture's class.)
       */
      nir_alu_type value_type = tex_dest_type(c, in->operands[arg]->type, n);
      nir_def *value = air_get_ssa(c, in->operands[arg++]);
      if (!value)
         return false;
"""

OLD_SRC_TYPE = """                      .image_dim = t.dim, .image_array = t.is_array,
                      .src_type = dest_type);
      return true;
   }
"""

NEW_SRC_TYPE = """                      .image_dim = t.dim, .image_array = t.is_array,
                      .src_type = value_type);
      return true;
   }
"""

MARKER = "The store's type is the VALUE's"


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser(
        "~/fkernel/xnu-deps/build/mesa/mesa-25.0.7")
    path = os.path.join(root, "src", "compiler", "air", "air_intrinsics.c")
    if not os.path.isfile(path):
        sys.exit("air-store-type: no %s" % path)

    src = io.open(path, encoding="utf-8").read()
    if MARKER in src:
        print("air-store-type: %s is already patched" % path)
        return 0

    for old, new, what in ((OLD, NEW, "the image write"),
                           (OLD_SRC_TYPE, NEW_SRC_TYPE, "the store's src_type")):
        if old not in src:
            sys.exit("air-store-type: %s not found in %s (another front end?)" % (what, path))
        src = src.replace(old, new, 1)

    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("air-store-type: patched %s" % path)
    print("air-store-type: rebuild libair.a in the iOS and host Mesa builds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
