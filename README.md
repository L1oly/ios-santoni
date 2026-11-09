# ios-santoni

**Apple's iOS 16 running on a Xiaomi Redmi 4X (`santoni`).**

This is a port of [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)
(Apple's open-source XNU kernel, `xnu-8796`, on a Redmi Note 10 Pro) to the
Xiaomi **Redmi 4X** (`santoni`, Qualcomm **MSM8940 / Snapdragon 435**), on top of
the [`console-ramoops/ios-santoni`](https://github.com/console-ramoops/ios-santoni)
santoni work. The same SoC family covers the **Redmi 5A** (`riva`).

On top of the kernel runs the **unmodified iOS 16.7.16 (20H392) userland of the
iPhone X**: launchd, the system daemons, backboardd and SpringBoard.

The iPhone X is the newest iOS that still ships an `arm64` (non-PAC) userland,
which is what a Cortex-A53 can execute. iOS 17 and later dropped every non-PAC
device, so 16.7.16 is the ceiling here — see [Why iOS 16.7](#why-ios-167).

> Experimental bring-up, not a usable phone OS. Apple's security model is
> mostly switched off. The root lives in `userdata`, so **Android's user data is
> erased**. Nothing is written to the boot partitions: the kernel is started
> from RAM with `fastboot boot`.

## Status (2026-11-09)

The kernel boots on real hardware, mounts the iOS root from **eMMC**, and
`launchd` runs as PID 1 with the iPhone X dyld shared cache mapped:

```
exec launchd
com.apple.xpc.launchd <Notice>: Darwin Bootstrapper Version 7.0.0
com.apple.xpc.launchd <Notice>: entering ondemand mode
com.apple.xpc.launchd <Notice>: (mount-phase-1) Doing boot task
/dev/emmcroot0 on / (hfs, local, journaled, noatime)
```

It currently stops in `mount-phase-1`:

```
mount: failed to mount /private/preboot/<uuid>/usr/standalone/firmware
  -> /usr/standalone/firmware - Operation not supported by device(19)
pid 2 exited -- (signal 0, exit 74)
```

ENODEV means the kernel has no `bindfs`. The SANTONI kernel config was copied
from the sweet config as it stood before the `bindfs` patch, so it lacked it;
`xnu/patches/0085-santoni-board-target.patch` now matches sweet's proven
`FILESYS_BASE` exactly and a CI rebuild is pending. There is no fstab entry to
disable: launchd computes that preboot path itself.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Xiaomi ABL → `fastboot boot` of our shim (Android boot image v0, RAM only) → XNU |
| CPU | Boot CPU is cluster 1 core 0 (MPIDR `0x100`); PSCI `CPU_ON`, SGI and the ARM generic timer are verified. **1 of 8 cores** (see below) |
| MMU | 4 KiB granule, `TGran16 = 0`; the shim programs a 36-bit VA/IPS (the core reports `PARange = 2`, i.e. 40-bit capable), the kernel uses a 39-bit VA |
| Interrupts | GICv2 through MMIO (`GICD 0x0b000000`, `GICC 0x0b002000`), virtual timer INTID 20 at 19.2 MHz |
| Storage | SDHCI/eMMC (`sdcc1` at `0x07824900`, GCC `sdcc1_apps_clk_src` at `0x01842000`), 25 MHz 8-bit high-speed; GPT → `userdata` exposed as `emmcroot0`, journaled HFS+, read/write |
| iOS userland | Real iPhone X 16.7.16 root filesystem; `launchd` and its boot tasks run; the 44-file dyld shared cache maps |
| Display | 720×1280 24-bit BGR framebuffer left lit by ABL at `0x90001000`; the kernel console draws into it |
| Logging | `sweetlog=1` keeps a 4 MiB persistent console ring on the `system` partition |
| Device identity | iPhone X (`iPhone10,3` / `D22AP`): no Home button, gesture UI, 360×640 points at 2× |

## What does not work (yet)

- **SpringBoard / backboardd / the GUI.** Blocked at `mount-phase-1` (above).
  After that, the sweet userland walls apply: CoreAnimation has no GPU and the
  kernel must present IOSurfaces on the CPU.
- **Touch and buttons**, **Wi-Fi, Bluetooth, cellular, audio, camera, sensors,
  GPS, SEP, real-time clock, GPU.** None of this hardware is driven.
- **Only 1 of 8 cores** is started (`cpus=` is not set). The ADT lists all
  eight; PSCI bring-up of the rest is not verified on this phone.
- **Security is off**: permissive AMFI, sandbox logging only, `cs_enforcement_disable=1`,
  a patched `dyld` that ignores the shared cache's 16 KiB page signature.

## How santoni differs from sweet

Each of these stops the boot silently if missed.

| Problem | Fix |
| --- | --- |
| Cortex-A53 has **no 16 KiB translation granule**; XNU and the iOS userland are 16 KiB-native | XNU is built for **4 KiB pages** from the `SANTONI` MASTER config, with a 4 KiB bootstrap pmap, a user-VA cap and a smaller zone map (patches 0082, 0084, 0093, 0097). The kernel links at `0x98000000` with a 640 MiB budget |
| **GICv2, not GICv3**: there are no `ICC_*_EL1` system registers | `xnu/patches/0017-santoni-gicv2-rtclock.patch` drives the memory-mapped distributor and CPU interface, routes the virtual timer (INTID 20) through the IRQ path, and masks the CPUID bits out of `IAR`; `shim/gic.c` prepares the same controller before the jump |
| **eMMC, not UFS**: the sweet storage driver speaks UFS/SCSI | `xnu/patches/0142-santoni-sdhci-emmc-driver.patch` is a polled SDHCI PIO driver: CMD0/1/2/3/8/9/7 enumeration, EXT_CSD, 25 MHz/8-bit/high-speed switch, CMD17/18/25 with `AUTO_CMD12`, GPT parsing and a BSD disk (`emmcroot0`, char device `remmcroot0`) |
| The core is **ARMv8.0**: no LSE atomics, no RCpc, no PAN | `-mcpu=cortex-a53 -march=armv8-a+crypto`, PAN disabled, commpage PFZ without `casa`, and the sweet `LSE`/`LDAPR` userland emulation compiled in (patches 0094, 0095, 0096, 0081) |
| Different MMIO map and panel | GIC `0x0b000000`/`0x0b002000`, eMMC `0x07824900`, GCC `0x01842000`, framebuffer `0x90001000` (720×1280×3, stride 2160), kernel RAM `0x98000000` |
| The dyld cache is signed for 16 KiB pages and has no usable CS blob | patch 0144 leaves it blob-less and the boot-arg `cs_enforcement_disable=1` switches off the macOS-target shared-cache checks; `/usr/lib/dyld` is patched in the root image to skip its own coverage check (its own CodeDirectory is 4 KiB) |

## How it boots

```
ABL (stock Xiaomi bootloader, unlocked)
  -> fastboot boot shim-boot.img          (boot image v0, RAM only)
     -> shim: MMU/4K bootstrap, DTB lookup, GICv2 + timer test,
        diagnostics on the red screen, finds the SWEETXNU payload
        -> XNU Mach-O + Apple Device Tree + boot-args
           -> XNU -> SDHCI/eMMC -> HFS+ root in userdata
              -> dyld + shared cache -> launchd -> (backboardd, SpringBoard)
```

There is no serial console. The shim and the kernel draw into ABL's 720×1280
framebuffer. The kernel also keeps a persistent log ring (see
[Debugging](#debugging)).

## How to do it yourself

You need a Redmi 4X (`santoni`, MSM8940; the 3/32 GB variant is what this was
developed on) with an **unlocked bootloader**, a Linux PC with `fastboot`, and a
GitHub account for the kernel build. **Everything on `userdata` is lost.** Boot,
recovery, modem, persist and firmware partitions are never written.

### 1. Build the kernel

The kernel builds on GitHub's macOS runners with
[blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build).
`macos-14` (Xcode 15) is retired; the workflow now uses `macos-15` with its
oldest Xcode (16.0) and `tools/sweet-iig-compat.py`, which rewrites the one
generated construct (`IORPC.kernelContent`) that Xcode 16's `iig` emits and
`xnu-8796` does not have. The kernel `IORPC` layout and dispatch ABI are
unchanged.

Fork the repo, push this branch, and either let the push trigger the `xnu`
workflow or run it manually:

```sh
gh workflow run xnu.yml -R YOU/ios-santoni --ref santoni -f machine_config=SANTONI
gh run download RUN_ID -R YOU/ios-santoni -n xnu-kernel -D xnu/out
```

The artifact is `kernel.development.santoni`. Without `gh`, the artifact is at
`https://nightly.link/YOU/ios-santoni/workflows/xnu/santoni/xnu-kernel.zip`
once the run is green. A cold build is long (the job allows 120 minutes).

If GitHub cannot allocate a runner ("The job was not acquired by Runner of type
hosted"), that is capacity, not a build error — no step runs. Re-run it, or
dispatch on another pool. `macos-15` is the Intel image and `macos-15-arm64` is
Apple Silicon; `macos-26` and `macos-26-arm64` ship Xcode 26 only (the IIG
adapter and patch 0145 handle it). All four cross-build the same arm64 kernel:

```sh
gh workflow run xnu.yml -R YOU/ios-santoni --ref santoni -f runner=macos-15-arm64
```

### 2. Build the iOS root image

Download the iPhone X (iPhone10,3) iOS 16.7.16 (20H392) IPSW from Apple. On
Linux, with `apfs-fuse` (build it from
[sgan81/apfs-fuse](https://github.com/sgan81/apfs-fuse) if your distribution has
no package), `hfsprogs` and sudo:

```sh
# OS, SystemOS and AppOS disk images (see BuildManifest.plist, D22AP identity)
sudo bash tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G
sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot
sudo python3 tools/sweet-root-tweaks.py /mnt/iosroot
sudo umount /mnt/iosroot
img2simg ios16-root.img ios16-root.simg
```

`sweet-root-tweaks.py` applies the bring-up changes: no panic on daemon crashes,
no CommCenter (no baseband), containers, no data migration, Setup skipped,
SpringBoard watchdogs off, activation seeded.

The device tree builder copies `/product` from the real iPhone X device tree.
Take `Firmware/all_flash/DeviceTree.d22ap.im4p` from the IPSW, decompress its
LZFSE payload (`ipsw img4 im4p extract`) and save it as
`research/ipsw-x/d22ap.adt`.

### 3. Build the boot image

Needs `clang`/`ld.lld` (aarch64 target) and `tools/mkbootimg.py`.

```sh
python3 tools/mkadt.py shim/out/santoni.adt
python3 tools/mkpayload.py kernel.development.santoni shim/out/santoni.adt shim/out/payload.bin \
  --cmdline 'debug=0x14e serial=3 disable_kprintf_output=0 -enable_kprintf_spam sweetfb_native=1 sweetcpufreq=0 sweetbattery=0 rd=emmcroot0 sweetlog=1 unentitled_ios_sim_launch=1 ignition_level=1 launchd_unsecure_cache=1 cs_enforcement_disable=1 wdt=-1 wdt_test=no_user_checkin emmcrw=1 rootrw=1 -v keepsyms=1 santoni'
bash shim/build.sh shim/out/payload.bin      # -> shim/out/shim-boot.img
```

`shim/build.sh` appends `resources/santoni_appended_dtbs.bin` (29 Qualcomm
DTBs, including `msm8940-xiaomi-santoni`) so the bootloader can find the DTB,
and packs everything as an Android boot image v0 based at `0x80000000`.

| Boot-arg | Effect |
| --- | --- |
| `rd=emmcroot0 emmcrw=1 rootrw=1` | Root on `userdata` through the SDHCI driver, writable |
| `sweetfb_native=1` | Present the real 720×1280 panel instead of the iPhone X canvas |
| `sweetlog=1` | Keep the persistent console ring on the `system` partition |
| `unentitled_ios_sim_launch=1`, `launchd_unsecure_cache=1` | launchd without AMFI / signed-cache entitlement |
| `cs_enforcement_disable=1` | Skip the macOS-target shared-cache CS checks (see below) |
| `wdt=-1 wdt_test=no_user_checkin` | No hardware watchdog |
| `sweetcpufreq=0 sweetbattery=0` | Do not probe the sweet PMIC/cpufreq drivers |
| `-v keepsyms=1` | Kernel console text and symbols |

### 4. Flash the root and boot

```sh
fastboot -S 512M flash userdata ios16-root.simg   # ~5 minutes; do not unplug
fastboot boot shim/out/shim-boot.img
```

The shim shows its diagnostics (red screen: `MMFR0`, MMU, PSCI, GIC, timer) for
a few seconds, then XNU starts and prints on the panel. To get back to fastboot,
hold **Power + Volume Down**.

A boot in read-write mode changes `userdata` (journal replay, HFS+ hard-link
bits), so the flashed image no longer byte-matches the file on disk. Rebuild or
keep a pristine copy if you plan to reflash.

## Debugging

- **Panel console.** The kernel draws its console into the ABL splash framebuffer
  (720×1280, 24-bit BGR at `0x90001000`, stride 2160). Panics are drawn too.
- **Persistent ring.** With `sweetlog=1` the last 4 MiB of console output live at
  the end of the `system` partition (`mmcblk0p24`). Boot a recovery that gives
  you `adb` (TWRP), then:

  ```sh
  adb exec-out "dd if=/dev/block/mmcblk0p24 bs=512 count=8193" > santonilog.bin
  python3 tools/sweet-log.py santonilog.bin boot.txt
  ```

  This survives panics and reboots and is the main way this port is debugged.
- **Shared-cache symbols.** `tools/sweet-crash.py` symbolicates crash reports
  against the iPhone X dyld shared cache.

## Why iOS 16.7

The iOS version *is* the XNU version: 16 → `xnu-8796`, 17 → `xnu-10002`,
18 → `xnu-11215`, 26 → `xnu-12377+`. iOS 17 dropped the iPhone X, the last
device without pointer authentication, so every iOS 17+ userland is `arm64e`
(A12+ PAC). A Cortex-A53 is ARMv8.0: no PAC. On top of that, the whole santoni
port — 4 KiB pages, GICv2, the eMMC driver, the board config — is written
against `xnu-8796`. iOS 16.7.16 is therefore both the hardware ceiling and the
only version this patch series targets.

## Repository layout

| Path | What |
| --- | --- |
| `shim/` | Bare-metal boot shim (C + asm): 4 KiB MMU bootstrap, DTB, GICv2/timer, payload loader, framebuffer console |
| `xnu/patches/` | XNU patch series, applied in order by CI (sweet 0001–0079, topaz 0080–0139, santoni 0140–0144) |
| `.github/workflows/xnu.yml` | Kernel CI (`macos-15`, `MACHINE_CONFIG=SANTONI`) |
| `tools/mkadt.py` | Apple Device Tree for santoni (CPUs, memory, GICv2, SDHCI, panel) and the iPhone X identity |
| `tools/mkpayload.py` | Packs kernel + ADT + boot-args into the `SWEETXNU` payload |
| `tools/mkiosroot.sh`, `tools/sweet-root-tweaks.py` | Build and adjust the HFS+ iOS root |
| `tools/sweet-log.py`, `tools/sweet-crash.py` | Read the persistent log ring, symbolicate crashes |
| `resources/santoni_appended_dtbs.bin` | Qualcomm DTB table appended to the shim image |
| `NOTES.md` | Engineering log of the port |

Not in git: partition backups, Apple firmware, IPSWs and root images, build
trees.

## santoni kernel patches

| # | What |
| --- | --- |
| 0017 | GICv2 MMIO interrupt controller and virtual timer (INTID 20) |
| 0082 | 4 KiB entry path (no `__ARM_16K_PG__`) |
| 0084 | 4 KiB user-VA cap |
| 0085 | `SANTONI` MASTER config and board target |
| 0093 | 39-bit kernel VA |
| 0094 | Cortex-A53 codegen (`-mcpu=cortex-a53 -march=armv8-a+crypto`) |
| 0095 | PAN off |
| 0096 | Commpage LL/SC without `casa` |
| 0097 | Zone map size for a 3 GB phone |
| 0098, 0140 | 720×1280 BGR early console / kprintf |
| 0141 | Do not probe the topaz battery/cpufreq drivers |
| 0142 | SDHCI/eMMC root driver |
| 0143 | Persistent console log ring on `system` |
| 0144 | 4 KiB-unsigned dyld shared cache |

## Key hardware facts (santoni)

- SoC MSM8940 / Snapdragon 435: 8× Cortex-A53, two clusters (MPIDR `0x000`–`0x003`
  and `0x100`–`0x103`), ARMv8.0, **4 KiB pages only** (`TGran16 = 0`), 40-bit PA
  (the shim maps with a 36-bit IPS).
- GICv2 at `0x0b000000` (distributor) / `0x0b002000` (CPU interface), 19.2 MHz
  generic timer, virtual timer INTID 20.
- RAM 3 GB at `0x80000000`; the kernel is loaded at `0x98000000` with a 640 MiB
  budget.
- eMMC: SDHCI `0x07824900` (inside the `0x07824000` core block), GCC
  `sdcc1_apps_clk_src` `0x01842000`, 8-bit bus, 25 MHz high-speed.
- Partitions: `system` = `mmcblk0p24` (log ring), `userdata` = `mmcblk0p49`
  (iOS root), ~24.5 GiB.
- Panel: 720×1280 24-bit BGR, splash left lit by ABL at `0x90001000`.

## Credits

Based on [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet), which
did the hard part: XNU on a Qualcomm phone with the iPhone X userland, and on the
[`console-ramoops/ios-santoni`](https://github.com/console-ramoops/ios-santoni)
santoni bring-up. Built on Apple's open-source releases (xnu, IOHIDFamily,
libpthread, hfs), [BearSSL](https://bearssl.org),
[blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build),
[ipsw](https://github.com/blacktop/ipsw), and Qualcomm/Xiaomi's published Linux
kernel sources for the hardware details. iOS itself is Apple's and is not
distributed here.
