#!/usr/bin/env python3
"""Let an insertvalue descend through a field an undef aggregate has not got yet.

LLVM names a nested field directly when it builds a struct up from `undef`:

    %57 = insertvalue %struct.TextureFetcher undef, ptr addrspace(1) %1, 0, 0
    %58 = insertvalue %struct.TextureFetcher %57, ptr addrspace(2) %6, 1, 0

with

    %struct.TextureFetcher = type { %"struct.metal::texture2d.3", %"struct.metal::sampler" }
    %"struct.metal::texture2d.3" = type { ptr addrspace(1) }

-- index 0 of the struct is the one-field wrapper `metal::texture2d`, and index 0
-- of THAT is the pointer. The value between the two is a field of `undef`, which
-- our aggregate tree leaves NONE, so the walk to `[0][0]` stopped at
--
--     instruction: an aggregate index out of its value
--
-- and the whole kernel was refused. This is how MetalPerformanceShaders builds
-- every texture it takes as a value: 245 of the iOS 16.5 image's 3,128 kernels
-- were refused for it (the largest single cause left after air-store-type.py),
-- and 3 of QuartzCore's.

The fix makes the aggregate the path descends through, of the type the struct
says, with its fields left NONE -- which is what undef means, so an extractvalue
that takes the same path still reads undef. Only an intermediate field is made:
the last one may legitimately be NONE, and both callers already handle that
(extractvalue yields undef, insertvalue assigns it).

hakios's published front end refuses the same modules (tools/mesa/air/
air_to_nir.c, the same message), so this is a gap to report upstream as well.

Run it after `xnu-deps/setup.sh`, then rebuild the AIR archive for both builds:

    python3 lemonadep/tools/air-agg-nested.py ~/fkernel/xnu-deps/build/mesa/mesa-25.0.7
    ninja -C ~/fkernel/xnu-deps/build/mesa/build-softpipe-freedreno \\
        src/compiler/air/libair.a
    ninja -C /root/mesa-host-build src/compiler/air/libair.a

Idempotent: a second run says so and exits 0.
"""

import io
import os
import sys

OLD = """/* an aggregate value's field, by the index path of extract/insertvalue */
static struct air_val **
agg_slot(struct air_ctx *c, struct air_val *agg, const uint32_t *idx, unsigned n)
{
   /* extractvalue and insertvalue always carry at least one index. Without this
    * the loop below never runs and the function returns the address of its own
    * parameter -- which gcc points out (-Wreturn-local-addr) and which would be
    * a write through a dead stack slot if anything ever took the path.
    */
   if (!n) {
      air_error(c, "instruction: an aggregate access with no index");
      return NULL;
   }
   struct air_val **slot = &agg;
   for (unsigned i = 0; i < n; i++) {
      if (!*slot || (*slot)->kind != AIR_VAL_AGG || idx[i] >= (*slot)->num_elems) {
         air_error(c, "instruction: an aggregate index out of its value");
         return NULL;
      }
      slot = &(*slot)->elems[idx[i]];
   }
   return slot;
}
"""

NEW = """/* The field of an aggregate type, or NULL when the type has no such field.
 * The index path of extractvalue/insertvalue names fields of fields, and the
 * values in between are not always there: see agg_slot.
 */
static const struct air_type *
agg_elem_type(const struct air_type *t, uint32_t i)
{
   if (!t)
      return NULL;
   if (t->kind == AIR_TYPE_STRUCT)
      return i < t->num_members ? t->members[i] : NULL;
   if (t->kind == AIR_TYPE_ARRAY)
      return i < t->count ? t->elem : NULL;
   return NULL;
}

static unsigned
agg_num_elems(const struct air_type *t)
{
   return t->kind == AIR_TYPE_STRUCT ? t->num_members : (unsigned)t->count;
}

/* an aggregate value's field, by the index path of extract/insertvalue */
static struct air_val **
agg_slot(struct air_ctx *c, struct air_val *agg, const struct air_type *t,
         const uint32_t *idx, unsigned n)
{
   /* extractvalue and insertvalue always carry at least one index. Without this
    * the loop below never runs and the function returns the address of its own
    * parameter -- which gcc points out (-Wreturn-local-addr) and which would be
    * a write through a dead stack slot if anything ever took the path.
    */
   if (!n) {
      air_error(c, "instruction: an aggregate access with no index");
      return NULL;
   }
   struct air_val **slot = &agg;
   for (unsigned i = 0; i < n; i++) {
      const struct air_type *elem = agg_elem_type(t, idx[i]);
      if (!*slot) {
         /* A field an undef aggregate has not got yet. LLVM names the nested
          * field directly when it builds a struct up from undef:
          *
          *   %56 = insertvalue %struct.TextureWriter undef, ptr addrspace(1) %0, 0, 0
          *   %57 = insertvalue %struct.TextureFetcher undef, ptr addrspace(1) %1, 0, 0
          *
          * -- index 0 of the struct is the one-field wrapper metal::texture2d,
          * and index 0 of THAT is the pointer -- and 245 of the iOS 16.5 image's
          * kernels (MetalPerformanceShaders') build their textures this way, as
          * do 3 of QuartzCore's.
          *
          * On the way DOWN to a deeper field, the aggregate the path descends
          * through is made here, of the type the struct says, with its fields
          * left NONE -- which is what undef means, so an extractvalue that takes
          * the same path still reads undef. The LAST field may legitimately be
          * NONE and is left alone: extractvalue reads it as undef and insertvalue
          * assigns it, both of which the callers already do.
          */
         if (i + 1 < n) {
            if (!elem || (elem->kind != AIR_TYPE_STRUCT && elem->kind != AIR_TYPE_ARRAY)) {
               air_error(c, "instruction: an aggregate index out of its value");
               return NULL;
            }
            *slot = air_val_agg(c, agg_num_elems(elem));
         } else {
            /* the last field of an undef aggregate: hand the caller the address
             * of the NONE itself, which is what it reads or writes */
            return slot;
         }
      } else if ((*slot)->kind != AIR_VAL_AGG || idx[i] >= (*slot)->num_elems) {
         air_error(c, "instruction: an aggregate index out of its value");
         return NULL;
      }
      slot = &(*slot)->elems[idx[i]];
      t = elem;
   }
   return slot;
}
"""

# the two callers, which now pass the type the path walks
CALLERS = [
    ("""      struct air_val **slot = agg_slot(c, agg, in->indices, in->num_indices);""",
     """      struct air_val **slot = agg_slot(c, agg, in->operands[0]->type,
                                       in->indices, in->num_indices);"""),
    ("""      struct air_val **slot = agg_slot(c, copy, in->indices, in->num_indices);""",
     """      struct air_val **slot = agg_slot(c, copy, in->operands[0]->type,
                                       in->indices, in->num_indices);"""),
]

MARKER = "agg_elem_type"


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.expanduser(
        "~/fkernel/xnu-deps/build/mesa/mesa-25.0.7")
    path = os.path.join(root, "src", "compiler", "air", "air_to_nir.c")
    if not os.path.isfile(path):
        sys.exit("air-agg-nested: no %s" % path)

    src = io.open(path, encoding="utf-8").read()
    if MARKER in src:
        print("air-agg-nested: %s is already patched" % path)
        return 0

    if OLD not in src:
        sys.exit("air-agg-nested: agg_slot() is not the expected one in %s "
                 "(another front end?)" % path)
    src = src.replace(OLD, NEW, 1)

    for old, new in CALLERS:
        if old not in src:
            sys.exit("air-agg-nested: a caller of agg_slot() was not found in %s" % path)
        src = src.replace(old, new, 1)

    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("air-agg-nested: patched %s" % path)
    print("air-agg-nested: rebuild libair.a in the iOS and host Mesa builds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
