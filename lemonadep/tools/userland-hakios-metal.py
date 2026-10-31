#!/usr/bin/env python3
"""Put HakiOS's Metal driver (hakios-metal) into our userland tree.

What it changes, in <tree>/userland (the furangelz/hackios tree the lab builds):

  build.sh   builds HakiosMetal.bundle from hakios-metal's plugin/ and links its core
             (libhakios-metal.a) with the Mesa archives the shader compiler needs; installs
             the bundle into /redwood/lib; writes HakiosMetal.clients; links the bundle into
             /System/Library/Extensions (where Metal's discovery looks); copies the probe into
             /redwood/bin.
  src/hakios_metal_plugin.plist   the bundle's Info.plist (NSPrincipalClass HakiosMetalDevice).
  rc.jobs.hakiosmetal             the RC_JOBS file for the first boot (metal_props on, metal_test,
                                  the probe, metal_props off).

The port's own RedwoodMetal plug-in stays where it is: this adds a second bundle beside it, and
nothing composes either path until a process puts MetalPluginName on the IOAcceleratorES service
(boot-arg metal=1).

Prerequisites: hakios-metal built for iOS 16.5 with the compiler (`make ios MESA=1 HAKIOS=<tree>`
in it), and lemonadep/tools/air-compat.py run over the Mesa tree that build used.

Idempotent: a second run says so and changes nothing.
"""

import io
import os
import sys

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>CFBundleIdentifier</key>
\t<string>com.hakios.metal</string>
\t<key>CFBundleName</key>
\t<string>HakiosMetal</string>
\t<key>CFBundleExecutable</key>
\t<string>HakiosMetal</string>
\t<key>CFBundlePackageType</key>
\t<string>BNDL</string>
\t<key>CFBundleInfoDictionaryVersion</key>
\t<string>6.0</string>
\t<key>CFBundleVersion</key>
\t<string>1</string>
\t<key>CFBundleSupportedPlatforms</key>
\t<array>
\t\t<string>iPhoneOS</string>
\t</array>
\t<!-- the class Metal takes (it also names it in MetalPluginClassName); made when the bundle is loaded -->
\t<key>NSPrincipalClass</key>
\t<string>HakiosMetalDevice</string>
</dict>
</plist>
"""

RC_JOB = """# Commands run by the launchd job com.redwood.demo (RC_JOBS=rc.jobs.hakiosmetal).
#
# The first boot where Metal's own discovery finds HakiOS's driver (github.com/oosexgang/hakios-metal)
# on lemonadep. The kernel has to be booted with metal=1: that is what lets a process put
# MetalPluginName and MetalPluginClassName on the IOAcceleratorES service
# (iokit/Kernel/MiniIOMobileFramebuffer.cpp), and it is also the level HakiOS's plug-in reads --
# level 1 shows the device only to the programs named in HakiosMetal.clients, which the image
# writes beside the bundle (metal_test and hakios-metal-probe).
#
# The GPU is the kernel's own RedwoodGPU service (boot-arg gpu=1); hakios-metal's transport asks for
# "RedwoodGPU" here. gpu_recover=1 belongs in the boot-args too: a dispatch the GPU never finishes is
# found by the wait's timeout alone, and without it the kernel waits for nothing again in that run.
#
# What each line is for:
#  - show/on: the two properties, set from a program that does not itself ask Metal (a half-made
#    device aborts the process that asks, and launchd restarts it -- docs/metal.md 10.14)
#  - metal_test: Metal's five discovery steps, from a program that loads none of this by hand
#  - hakios-metal-probe: the driver's own stages -- GEM buffers, blits, a dispatch, a draw, and what
#    only the real GPU can say. Its output is the log this boot exists for.
#  - off: the way back without a reboot
/redwood/bin/metal_props show
/redwood/bin/metal_props on HakiosMetal HakiosMetalDevice
/redwood/bin/metal_test
/redwood/bin/hakios-metal-probe
/redwood/bin/metal_props off
"""

BUILD_ANCHOR = """\t\t$DYN -bundle -framework Foundation -framework IOKit -framework Metal -lobjc \\
\t\t\t-o obj/RedwoodMetal src/redwoodmetal.m src/redwooddrawable.m
"""

BUILD_BLOCK = BUILD_ANCHOR + """
\t\t# HakiOS's Metal driver (github.com/oosexgang/hakios-metal), the same kind of bundle and the
\t\t# same discovery: its core libhakios-metal.a, over the kernel's own GPU service (RedwoodGPU
\t\t# here; the request numbers and structs are the same), with the shader compiler -- Mesa's AIR
\t\t# front end and ir3 -- linked in, because Apple's shaders are compiled on the phone. The Mesa
\t\t# archives are the ones ../tools/mk-mesa.sh builds; HAKIOS_MESA_BUILD= says otherwise.
\t\t# HAKIOS_METAL= says where the tree is (default /root/hakios-metal).
\t\tHM=${HAKIOS_METAL:-/root/hakios-metal}
\t\tHMB=${HAKIOS_MESA_BUILD:-../xnu-deps/build/mesa/build-softpipe-freedreno}
\t\tif [ -f "$HM/out/ios/libhakios-metal.a" ] && [ -f "$HMB/src/compiler/air/libair.a" ]; then
\t\t\t$DYN -bundle -lobjc -DHAKIOS_METAL_GPU -I"$HM/include" -o obj/HakiosMetal \\
\t\t\t\t"$HM/plugin/HakiosMetal.m" "$HM/plugin/hakios_metallib.c" \\
\t\t\t\t"$HM/out/ios/libhakios-metal.a" \\
\t\t\t\t"$HMB/src/compiler/air/libair.a" "$HMB/src/freedreno/ir3/libfreedreno_ir3.a" \\
\t\t\t\t"$HMB/src/freedreno/isa/libir3encode.a" "$HMB/src/freedreno/isa/libir3decode.a" \\
\t\t\t\t"$HMB/src/compiler/isaspec/libisaspec.a" "$HMB/src/compiler/nir/libnir.a" \\
\t\t\t\t"$HMB/src/compiler/libcompiler.a" "$HMB/src/freedreno/common/libfreedreno_common.a" \\
\t\t\t\t"$HMB/src/util/libmesa_util.a" "$HMB/src/util/libmesa_util_sse41.a" \\
\t\t\t\t"$HMB/src/util/blake3/libblake3.a" "$HMB/src/c11/impl/libmesa_util_c11.a" \\
\t\t\t\t-framework Foundation -framework Metal -framework IOKit -framework IOSurface \\
\t\t\t\t-framework CoreFoundation -lz -lm -lc++ ||
\t\t\t\techo "build.sh: HakiosMetal did not link (is hakios-metal's make ios MESA=1 done?)"
\t\tfi
"""

INSTALL_ANCHOR = """\tif [ -f obj/RedwoodMetal ]; then
\t\tmkdir -p root/lib/RedwoodMetal.bundle
\t\tcp obj/RedwoodMetal root/lib/RedwoodMetal.bundle/
\t\tcp src/metal_plugin.plist root/lib/RedwoodMetal.bundle/Info.plist
\tfi
"""

INSTALL_BLOCK = INSTALL_ANCHOR + """\tif [ -f obj/HakiosMetal ]; then
\t\tmkdir -p root/lib/HakiosMetal.bundle
\t\tcp obj/HakiosMetal root/lib/HakiosMetal.bundle/
\t\tcp src/hakios_metal_plugin.plist root/lib/HakiosMetal.bundle/Info.plist
\tfi
\t# Which programs are shown the device when the boot-arg says metal=1 (the safe level: metal_test
\t# only). HakiOS's plug-in reads this file beside the bundle (listedBesideTheBundle,
\t# plugin/HakiosMetal.m), the way UniXNU's AdrenoMetal picks its clients; the probe is the driver's
\t# own, so it is listed here rather than raising the level for every process on the machine.
\tif [ -f obj/HakiosMetal ]; then
\t\tprintf 'metal_test\\nhakios-metal-probe\\n' > root/lib/HakiosMetal.clients
\tfi
"""

PROBE_ANCHOR = "\t[ -f obj/metal_props ] && cp obj/metal_props root/bin/\n"

PROBE_BLOCK = PROBE_ANCHOR + """\t# the driver's own probe (hakios-metal): what the tests do on the fake GPU, on the real one -- blits,
\t# a dispatch and a draw -- then what only the phone can say. gpu_recover=1 belongs in the boot-args
\t# beside it (a dispatch the GPU never finishes is found by the wait's timeout alone).
\tHM=${HAKIOS_METAL:-/root/hakios-metal}
\t[ -f "$HM/out/ios/hakios-metal-probe" ] && cp "$HM/out/ios/hakios-metal-probe" root/bin/
"""

SYMLINK_ANCHOR = "\tln -s /redwood/lib/RedwoodMetal.bundle sysroot/System/Library/Extensions/RedwoodMetal.bundle\n"
SYMLINK_BLOCK = SYMLINK_ANCHOR + """\tln -s /redwood/lib/HakiosMetal.bundle sysroot/System/Library/Extensions/HakiosMetal.bundle
\t# The clients list is looked for beside the bundle *as it was loaded* (dladdr on the
\t# plug-in's own address, plugin/HakiosMetal.m listedBesideTheBundle): Metal composes
\t# /System/Library/Extensions/<name>.bundle and NSBundle loads the executable by that
\t# path, so the symlink's target directory is not where it looks. Both copies, because
\t# which path dyld records is not something to bet the first boot on.
\tprintf 'metal_test\\nhakios-metal-probe\\n' > sysroot/System/Library/Extensions/HakiosMetal.clients
"""


def main(argv):
    tree = argv[1] if len(argv) > 1 else os.path.expanduser("~/fkernel")
    userland = os.path.join(tree, "userland")
    build = os.path.join(userland, "build.sh")
    if not os.path.isfile(build):
        sys.exit("userland-hakios-metal: no %s" % build)

    src = io.open(build, encoding="utf-8").read()
    if "obj/HakiosMetal" in src:
        print("userland-hakios-metal: %s is already patched" % build)
        return 0

    for anchor, block, what in ((BUILD_ANCHOR, BUILD_BLOCK, "RedwoodMetal build"),
                                (INSTALL_ANCHOR, INSTALL_BLOCK, "RedwoodMetal install"),
                                (PROBE_ANCHOR, PROBE_BLOCK, "metal_props copy"),
                                (SYMLINK_ANCHOR, SYMLINK_BLOCK, "RedwoodMetal symlink")):
        if anchor not in src:
            sys.exit("userland-hakios-metal: %s anchor not found (build.sh moved?)" % what)
        src = src.replace(anchor, block, 1)

    io.open(build, "w", encoding="utf-8", newline="\n").write(src)
    io.open(os.path.join(userland, "src", "hakios_metal_plugin.plist"), "w",
            encoding="utf-8", newline="\n").write(PLIST)
    io.open(os.path.join(userland, "rc.jobs.hakiosmetal"), "w",
            encoding="utf-8", newline="\n").write(RC_JOB)
    print("userland-hakios-metal: patched %s" % build)
    print("userland-hakios-metal: wrote src/hakios_metal_plugin.plist and rc.jobs.hakiosmetal")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
