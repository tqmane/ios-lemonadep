#!/usr/bin/env python3
"""Make the GPU's fault report say *whose* address the SMMU refused, and whether its tables had it.

metal4.log (2026-11-01) left one question the address log could not answer. The address the SMMU
refused, 0x237b0040, was inside a live 11 MB buffer of the window server's (0x23780000..0x2423ffff)
that no `given back` line anywhere in the log covers, and no client's buffer was refused for want of
pages -- so the driver had mapped it, or says it had. Two very different bugs read the same in a log:

  * the page was never mapped (a freed hole, an allocator overlap, a wrong size), or
  * the page *was* mapped and the SMMU still had no entry for it (a table never written out of this
    processor's cache, a second tree, a stale unmap of a neighbour).

So this patch prints, at the fault itself (`space_faulted()`):

    adreno: 0: the tables for 0x237b0040: root[0x8] = 0x... (table 2), level2[0x1b] = 0x... (table 3),
              level3[0x3b] = 0xbf123000 | ...: a page, memory at 0xbf123000
    RedwoodGPU: 0x237b0040 is 0x30040 into buffer 37 of client 0xfffffff123456789 (0xac0000 bytes,
              flags 0x0): the driver says this address is mapped
    RedwoodGPU: the last submission the GPU took was client 0xfffffff123456789

Three statements, each of which rules something out: the entry is there or it is not; a buffer of
ours claims the address or none does; and the client whose stream the core is stopped in is named, so
"the probe's draw hung" and "the window server's draw killed the core" stop looking alike.

`xnu/files/` is what `xnu/apply.sh` copies in and `xnu-src/xnu-8796.121.2/` is the copy the build
reads: both are patched. Idempotent: a second run says so and exits 0.
"""

import io
import sys

MARKER = "is in no buffer the driver has mapped"

# --- xnu/files/iokit/Kernel/RedwoodGPU.cpp ------------------------------------------------------

CPP_EXTERN_OLD = """void RedwoodGPUStart(void);
void RedwoodGPUStop(void);"""

CPP_EXTERN_NEW = """void RedwoodGPUStart(void);
void RedwoodGPUStop(void);
/* the fault report's two answers: whose buffer an address is in, and whose submission is stopped */
void RedwoodGPUDescribeAddress(uint64_t address);
void RedwoodGPUDescribeSubmission(void);
void RedwoodGPUSubmitted(const void * client);"""

CPP_OWNERS_OLD = """	uint32_t                        fence;          /* the last submission that names it (0: none has) */
};"""

CPP_OWNERS_NEW = """	uint32_t                        fence;          /* the last submission that names it (0: none has) */
};

/*
 * The addresses this driver has entered into the GPU's, of every client, as plain copies: what the
 * fault report reads when the SMMU refuses an address (bsd/dev/redwood_adreno.c, space_faulted()).
 * Nothing here is dereferenced -- a client is a tag, a row is numbers -- because a report that can
 * fault is worse than no report. Rows are added where an address is mapped and dropped where it is
 * unmapped; a kept or left buffer's row stays, which is right: its pages are still mapped.
 */
struct gpu_owner {
	const void *                    client;
	uint32_t                        handle;
	uint32_t                        flags;
	uint64_t                        address, size;
};
#define GPU_OWNERS              1024
static struct gpu_owner gOwners[GPU_OWNERS];
static const void * gSubmitting;                /* the client whose submission the GPU took last */

static void
ownersAdd(const void * client, uint32_t handle, uint64_t address, uint64_t size, uint32_t flags)
{
	for (uint32_t i = 0; i < GPU_OWNERS; i++) {
		/* (a kept buffer given again is the same place under a new handle) */
		if (gOwners[i].size == size && gOwners[i].address == address) {
			gOwners[i].client = client;
			gOwners[i].handle = handle;
			gOwners[i].flags = flags;
			return;
		}
	}
	for (uint32_t i = 0; i < GPU_OWNERS; i++) {
		if (gOwners[i].size == 0) {
			gOwners[i].client = client;
			gOwners[i].handle = handle;
			gOwners[i].address = address;
			gOwners[i].size = size;
			gOwners[i].flags = flags;
			return;
		}
	}
}

static void
ownersDrop(uint64_t address, uint64_t size)
{
	for (uint32_t i = 0; i < GPU_OWNERS; i++) {
		if (gOwners[i].size == size && gOwners[i].address == address) {
			gOwners[i].size = 0;
		}
	}
}

void
RedwoodGPUDescribeAddress(uint64_t address)
{
	uint32_t said = 0;

	for (uint32_t i = 0; i < GPU_OWNERS; i++) {
		if (gOwners[i].size == 0 || address < gOwners[i].address ||
		    address - gOwners[i].address >= gOwners[i].size) {
			continue;
		}
		IOLog("RedwoodGPU: %#llx is %#llx into buffer %u of client %p (%#llx bytes, flags %#x): the driver says this address is mapped\\n",
		    address, address - gOwners[i].address, gOwners[i].handle, gOwners[i].client, gOwners[i].size,
		    gOwners[i].flags);
		said++;
	}
	if (said == 0) {
		IOLog("RedwoodGPU: %#llx is in no buffer the driver has mapped\\n", address);
	} else if (said > 1) {
		IOLog("RedwoodGPU: %u live buffers claim %#llx: they overlap\\n", said, address);
	}
}

/* Once per submission the GPU takes: whose stream the core may be stopped in. */
void
RedwoodGPUSubmitted(const void * client)
{
	gSubmitting = client;
}

void
RedwoodGPUDescribeSubmission(void)
{
	IOLog("RedwoodGPU: the last submission the GPU took was client %p\\n", gSubmitting);
}"""

CPP_NEWBUF_OLD = """	fBufferCount++;
	fBufferBytes += size;
	return b;
}"""

CPP_NEWBUF_NEW = """	fBufferCount++;
	fBufferBytes += size;
	ownersAdd(this, *handle, b->address, b->size, b->flags);
	return b;
}"""

CPP_KEEP_OLD = """			gGPUStat.given_again++;
			IOLockUnlock(gGPULock);"""

CPP_KEEP_NEW = """			gGPUStat.given_again++;
			ownersAdd(this, h + 1, b->address, b->size, b->flags);
			IOLockUnlock(gGPULock);"""

CPP_FREEBUF_OLD = """		} else if (redwood_gpu_ready()) {
			redwood_gpu_unmap(b->address, b->size);
			redwood_gpu_address_free(b->address, b->size);
		}"""

CPP_FREEBUF_NEW = """		} else if (redwood_gpu_ready()) {
			ownersDrop(b->address, b->size);
			redwood_gpu_unmap(b->address, b->size);
			redwood_gpu_address_free(b->address, b->size);
		}"""

CPP_NEWBUF_FAIL_OLD = """	if (!mapped) {
		redwood_gpu_unmap(b->address, size);
		redwood_gpu_address_free(b->address, size);"""

CPP_NEWBUF_FAIL_NEW = """	if (!mapped) {
		ownersDrop(b->address, size);
		redwood_gpu_unmap(b->address, size);
		redwood_gpu_address_free(b->address, size);"""

CPP_REAP_OLD = """		} else if (redwood_gpu_ready()) {
			redwood_gpu_unmap(left->address, left->size);
			redwood_gpu_address_free(left->address, left->size);
		}"""

CPP_REAP_NEW = """		} else if (redwood_gpu_ready()) {
			ownersDrop(left->address, left->size);
			redwood_gpu_unmap(left->address, left->size);
			redwood_gpu_address_free(left->address, left->size);
		}"""

CPP_DROPKEPT_OLD = """		redwood_gpu_unmap(k->address, k->size);
		redwood_gpu_address_free(k->address, k->size);"""

CPP_DROPKEPT_NEW = """		ownersDrop(k->address, k->size);
		redwood_gpu_unmap(k->address, k->size);
		redwood_gpu_address_free(k->address, k->size);"""

# (the same call is there twice: in the submission proper and in the retry after a ring-full reset --
# the first is the one that starts a stream, and both are this client's)
CPP_SUBMIT_OLD = """	request->fence = redwood_gpu_submit(addresses, words, count);
	/*
	 * The ring is full and the core is not reading it: it has stopped."""

CPP_SUBMIT_NEW = """	request->fence = redwood_gpu_submit(addresses, words, count);
	RedwoodGPUSubmitted(this);
	/*
	 * The ring is full and the core is not reading it: it has stopped."""

# --- xnu/files/bsd/dev/redwood_adreno.c ---------------------------------------------------------

C_MARKER = "RedwoodGPUDescribeAddress(far)"

C_FAR_OLD = """	printf("adreno: %u: THE SMMU REFUSED %s: status %#x, address %#llx, syndrome %#x\\n", step, space->name, status,
	    (uint64_t)rd(smmu.base + context + SMMU_CB_FAR + 4) << 32 | rd(smmu.base + context + SMMU_CB_FAR),
	    rd(smmu.base + context + SMMU_CB_FSYNR0));"""

C_FAR_NEW = """	uint64_t far = (uint64_t)rd(smmu.base + context + SMMU_CB_FAR + 4) << 32 | rd(smmu.base + context + SMMU_CB_FAR);

	printf("adreno: %u: THE SMMU REFUSED %s: status %#x, address %#llx, syndrome %#x\\n", step, space->name, status,
	    far, rd(smmu.base + context + SMMU_CB_FSYNR0));
	/* whether its own tables had the page, whose buffer it was, and whose submission the core is in */
	space_entries(space, far);
	RedwoodGPUDescribeAddress(far);
	RedwoodGPUDescribeSubmission();"""

C_ENTRIES_OLD = """static bool
space_faulted(const struct gpu_space *space)
{"""

C_ENTRIES_NEW = """/*
 * The SMMU's own tables for an address, read back the way its hardware would read them: present or
 * not, and where they point. A fault on a page the tables call mapped and a fault on a page nobody
 * mapped are different bugs with the same line in a log (2026-11-01: metal4.log's 0x237b0040 was
 * inside a live buffer of the driver's, and this is what says whether the SMMU agreed).
 */
static void
space_entries(const struct gpu_space *space, uint64_t address)
{
	uint64_t l2e, l3e, *l2 = NULL, *l3 = NULL;
	int32_t l2i = -1, l3i = -1;

	if (space->root == NULL) {
		printf("adreno: %s has no page tables\\n", space->name);
		return;
	}
	l2e = space->root[address >> 30 & 0x1ff];
	for (uint32_t i = 0; i < space->table_count; i++) {
		if ((l2e & PTE_TABLE) && space->tables[i].phys == (l2e & PTE_ADDRESS)) {
			l2 = space->tables[i].table;
			l2i = (int32_t) i;
		}
	}
	printf("adreno: the tables for %#llx: root[%#llx] = %#llx", address, (address >> 30) & 0x1ff, l2e);
	if (l2 == NULL) {
		printf(": no level 2 table of ours behind it (%u made)\\n", space->table_count);
		return;
	}
	l3e = l2[address >> 21 & 0x1ff];
	for (uint32_t i = 0; i < space->table_count; i++) {
		if ((l3e & PTE_TABLE) && space->tables[i].phys == (l3e & PTE_ADDRESS)) {
			l3 = space->tables[i].table;
			l3i = (int32_t) i;
		}
	}
	printf(" (table %d), level2[%#llx] = %#llx", l2i, (address >> 21) & 0x1ff, l3e);
	if (l3 == NULL) {
		printf(": NO LINK TO A LEVEL 3, so %#llx is in no mapping of the SMMU's\\n", address);
		return;
	}
	printf(" (table %d), level3[%#llx] = %#llx: %s, memory at %#llx\\n", l3i, (address >> 12) & 0x1ff,
	    l3[address >> 12 & 0x1ff], (l3[address >> 12 & 0x1ff] & PTE_PAGE) ? "a page" : "NOT A PAGE",
	    l3[address >> 12 & 0x1ff] & PTE_ADDRESS);
}

static bool
space_faulted(const struct gpu_space *space)
{"""

C_EXTERN_OLD = """static uint32_t
smmu_context(const struct gpu_space *space)
{"""

C_EXTERN_NEW = """extern void RedwoodGPUDescribeAddress(uint64_t address);
extern void RedwoodGPUDescribeSubmission(void);

static uint32_t
smmu_context(const struct gpu_space *space)
{"""

# --- stage 2: IOLog did not reach the log, and "a page" alone does not say what the SMMU reads --

#
# metal5.log (14:27) carried the fault line and the table walk, but not the two IOLog lines the same
# function made: IOLog is buffered and what it held was lost with the run, while printf reaches the
# serial log at once (the adreno lines are there). And the walk said the leaf entry was *present*
# (0x27262ce43: a page, memory at 0x27262c000) while the SMMU said translation fault -- two
# statements that can both be true only if the SMMU is reading memory this processor has not written
# yet, or reading other tables. So the report reads the entries back through an uncached view (what
# the SMMU's walk sees) and prints the context registers it is translating with.

CPP_PRINT_PATCHES = [
    ('IOLog("RedwoodGPU: %#llx is %#llx into buffer %u of client %p (%#llx bytes, flags %#x): the driver says this address is mapped\\n",',
     'printf("RedwoodGPU: %#llx is %#llx into buffer %u of client %p (%#llx bytes, flags %#x): the driver says this address is mapped\\n",'),
    ('IOLog("RedwoodGPU: %#llx is in no buffer the driver has mapped\\n", address);',
     'printf("RedwoodGPU: %#llx is in no buffer the driver has mapped\\n", address);'),
    ('IOLog("RedwoodGPU: %u live buffers claim %#llx: they overlap\\n", said, address);',
     'printf("RedwoodGPU: %u live buffers claim %#llx: they overlap\\n", said, address);'),
    ('IOLog("RedwoodGPU: the last submission the GPU took was client %p\\n", gSubmitting);',
     'printf("RedwoodGPU: the last submission the GPU took was client %p\\n", gSubmitting);'),
]

C_MEMORY_OLD = """\tprintf(" (table %d), level3[%#llx] = %#llx: %s, memory at %#llx\\n", l3i, (address >> 12) & 0x1ff,
\t    l3[address >> 12 & 0x1ff], (l3[address >> 12 & 0x1ff] & PTE_PAGE) ? "a page" : "NOT A PAGE",
\t    l3[address >> 12 & 0x1ff] & PTE_ADDRESS);
}"""

C_MEMORY_NEW = """\tprintf(" (table %d), level3[%#llx] = %#llx: %s, memory at %#llx\\n", l3i, (address >> 12) & 0x1ff,
\t    l3[address >> 12 & 0x1ff], (l3[address >> 12 & 0x1ff] & PTE_PAGE) ? "a page" : "NOT A PAGE",
\t    l3[address >> 12 & 0x1ff] & PTE_ADDRESS);
\tspace_memory(l2e & PTE_ADDRESS, (uint32_t)(address >> 21 & 0x1ff), "the level 2 entry", l3e);
\tspace_memory(l3e & PTE_ADDRESS, (uint32_t)(address >> 12 & 0x1ff), "the level 3 entry", l3[address >> 12 & 0x1ff]);
\tprintf("adreno: the context: sctlr %#x, ttbr0 %#llx, and these tables start at %#llx; smr0 %#x, s2cr0 %#x\\n",
\t    rd(smmu.base + smmu_context(space) + SMMU_CB_SCTLR),
\t    (uint64_t)rd(smmu.base + smmu_context(space) + SMMU_CB_TTBR0 + 4) << 32 |
\t    rd(smmu.base + smmu_context(space) + SMMU_CB_TTBR0), (uint64_t)kvtophys((vm_offset_t)space->root),
\t    rd(smmu.base + SMMU_SMR(0)), rd(smmu.base + SMMU_S2CR(0)));
}"""

C_MEMORY_HELPER_OLD = """static void
space_entries(const struct gpu_space *space, uint64_t address)
{"""

C_MEMORY_HELPER_NEW = """/* One entry of a table, read the way the SMMU's walk reads it: from memory, not from this cache. */
static void
space_memory(uint64_t table_phys, uint32_t index, const char * what, uint64_t written)
{
\tvolatile uint64_t *memory = (volatile uint64_t *)ml_io_map_wcomb((vm_offset_t)table_phys, 4096);

\tif (memory == NULL) {
\t\tprintf("adreno: %s: no uncached view of %#llx to read it back through\\n", what, table_phys);
\t\treturn;
\t}
\tprintf("adreno: %s: memory holds %#llx, this processor wrote %#llx%s\\n", what, memory[index], written,
\t    memory[index] == written ? "" : " -- THEY DIFFER: the SMMU walked an entry never written out");
}

static void
space_entries(const struct gpu_space *space, uint64_t address)
{"""

PATCHES_CPP = [
    ("externs", CPP_EXTERN_OLD, CPP_EXTERN_NEW),
    ("owners", CPP_OWNERS_OLD, CPP_OWNERS_NEW),
    ("newBuffer", CPP_NEWBUF_OLD, CPP_NEWBUF_NEW),
    ("kept given again", CPP_KEEP_OLD, CPP_KEEP_NEW),
    ("freeBuffer", CPP_FREEBUF_OLD, CPP_FREEBUF_NEW),
    ("newBuffer refused", CPP_NEWBUF_FAIL_OLD, CPP_NEWBUF_FAIL_NEW),
    ("reap", CPP_REAP_OLD, CPP_REAP_NEW),
    ("dropKept", CPP_DROPKEPT_OLD, CPP_DROPKEPT_NEW),
    ("submit", CPP_SUBMIT_OLD, CPP_SUBMIT_NEW),
]

PATCHES_C = [
    ("externs", C_EXTERN_OLD, C_EXTERN_NEW),
    ("space_entries", C_ENTRIES_OLD, C_ENTRIES_NEW),
    ("the fault line", C_FAR_OLD, C_FAR_NEW),
]


def patch(path, patches, marker=MARKER):
    src = io.open(path, encoding="utf-8").read()
    if marker in src:
        print("%s: already patched" % path)
        return True
    for name, old, new in patches:
        if src.count(old) != 1:
            print("%s: %s: the expected text is there %d times, not once" % (path, name, src.count(old)))
            return False
        src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("%s: patched (%d places)" % (path, len(patches)))
    return True


def patch_pairs(path, pairs, marker):
    src = io.open(path, encoding="utf-8").read()
    if marker in src:
        print("%s: already patched (stage 2)" % path)
        return True
    for old, new in pairs:
        if src.count(old) != 1:
            print("%s: stage 2: the expected text is there %d times, not once: %r" % (path, src.count(old), old[:60]))
            return False
        src = src.replace(old, new, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("%s: patched (%d places, stage 2)" % (path, len(pairs)))
    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/root/fkernel"
    trees = ["xnu/files", "xnu-src/xnu-8796.121.2"]
    ok = True
    for tree in trees:
        cpp = "%s/%s/iokit/Kernel/RedwoodGPU.cpp" % (root, tree)
        c = "%s/%s/bsd/dev/redwood_adreno.c" % (root, tree)
        ok = patch(cpp, PATCHES_CPP, MARKER) and ok
        ok = patch(c, PATCHES_C, C_MARKER) and ok
        ok = patch_pairs(cpp, CPP_PRINT_PATCHES, "printf(\"RedwoodGPU: %#llx is in no buffer") and ok
        ok = patch_pairs(c, [(C_MEMORY_HELPER_OLD, C_MEMORY_HELPER_NEW), (C_MEMORY_OLD, C_MEMORY_NEW)], "space_memory(") and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
