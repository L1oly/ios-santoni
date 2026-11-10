# Agent handoff — ios-sweet / santoni

Long-form working notes for whoever picks this up. `AGENTS.md` is the short
pointer; this file and `NOTES.md` are the detail. `NOTES.md` is the
chronological engineering log (newest entry at the top) and is the authority on
hardware facts, patch numbers and past dead ends — read its top entry first.

## Goal

Run iOS 16.7.16 (20H392, iPhone X userland) on a Xiaomi Redmi 4X (`santoni`,
MSM8940/SD435, Cortex-A53, GICv2, eMMC, 3/32 GB). Fork of
`console-ramoops/ios-santoni`, branch `santoni`, pushed to
`git@github.com:L1oly/ios-santoni.git` (remote `mine`).

Current blocker: the dyld shared-cache slide wall. Root cause was found and
fixed (patch 0147, commit `eeb7ddc`) but the CI run that builds it failed; see
"Current state" below.

## How work is done here

- **Kernel builds only happen in CI** (GitHub Actions, `macos-15`, ~10 min).
  There is no local macOS. `gh` is not installed; poll the public REST API
  instead:
  - `https://api.github.com/repos/L1oly/ios-santoni/actions/runs?branch=santoni&per_page=3`
  - `https://api.github.com/repos/L1oly/ios-santoni/actions/runs/<id>/jobs`
  - Artifacts (no auth): `https://nightly.link/L1oly/ios-santoni/actions/runs/<id>/xnu-kernel.zip`
    and `.../xnu-buildtree.zip`
  - **Build logs are not reachable without auth** (403). If a run fails and the
    kernel artifact is empty, the error is in `build.log`, which is not
    uploaded — add it to the artifacts before spending more runs.
- **Patches** live in `xnu/patches/NNNN-santoni-*.patch` and are applied by
  dxb with `git apply --check`, which only *warns* on a bad patch. Always:
  1. `python3 tools/check_patch.py <patch>` (hunk counts exact),
  2. `patch -p1 --dry-run` against the pristine tree in
     `/home/l1oly/santoni-ios/opencode/xnu-xnu-8796.141.3`,
  3. regenerate with `git diff` in a scratch repo seeded with the
     already-patched file (never hand-edit hunk headers).
- **Local compile check** is possible without macOS: `tools/xnu-cc.py`
  needs a CI log, but the *build tree* artifact plus the component `Makefile`
  is enough to rebuild one command (`make -n <obj>.o` after rewriting
  `SOURCE_DIR`), then run clang with `-fsyntax-only -target
  arm64-apple-macos14.0 -nostdinc` and the tree's own headers. A Linux clang
  works for xnu sources; add `-Wno-unsafe-buffer-usage` and ignore
  `proc_reg.h: processor not supported` (toolchain differences).
- **Commits** must end with `Co-Authored-By: Gemini <noreply@google.com>`.
- Update the top entry of `NOTES.md` after each milestone: commits, CI run IDs,
  exact build/boot results, and what is still open. Say what was observed
  versus what is guessed.

## Device rules

- Bring-up uses `fastboot boot <img>` (never `fastboot flash`) so bootloaders,
  recovery, modem, persist and backups stay intact.
- The iOS root lives in the existing `userdata` partition (`mmcblk0p49`); no
  GPT changes. Android data was explicitly declared disposable (2026-10-15).
- Confirm each destructive step with the user first. Physical actions (Power +
  Volume Down for fastboot, USB replug) must be requested, not assumed.
- `system` (`mmcblk0p24`) is repurposed as the persistent kernel console ring:
  512 B `SANTONILOG1` header + 4 MiB ring at the start of the partition.
- Log pull: boot TWRP (`work/twrp-santoni.img`), then
  `adb exec-out "dd if=/dev/block/bootdevice/by-name/system bs=512 count=8193" > ring.bin`
  and decode with `tools/sweet-log.py ring.bin out.txt`.
  TWRP `dd` is toybox: `count` is in **blocks**.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.

## Local artifacts

| Path | What |
| --- | --- |
| `work/ios16-root.img` | 16 GiB HFS+ iOS root baseline (flashed to `userdata`) |
| `work/build-boot-emmc.sh` | `KERNEL=<path> bash work/build-boot-emmc.sh rw\|ro` |
| `work/twrp-santoni.img` | TWRP for log pulls and raw `dd` |
| `work/STATUS.md` | earlier status snapshot |
| `shim/out/shim-boot-emmc-rw.img` | last boot image built |
| `/tmp/opencode/k146/kernel.development.santoni` | last good instrumented kernel (`73f84ce`) |

## Current state (2026-11-10)

- iOS root flashed and mounted (`hfs: mounted iOSRoot`); dyld patch applied on
  the phone so the shared cache maps.
- `bindfs`/launchd walls passed: `mount-phase-2`, `init-with-data-volume`,
  `fips`, `exec SpringBoard`, `exec xpcproxy`.
- **Slide wall root cause (proven with patch 0146 diagnostics):**
  `santoni_sdhci_strategy()` released `santoni_sdhci_lock` before the
  `memcpy`/`copyout` out of the single shared bounce buffer, so a concurrent
  request refilled it and the copy moved another request's data into the
  caller's pages. Evidence: `so == want` (right object offset) but the 4096
  bytes were byte-identical to an unrelated image page at `0x244756000`;
  `sp != dp`, so not an alias.
- **Fix:** patch `0147-santoni-sdhci-bounce-lock.patch`, commit `eeb7ddc`
  (pushed). Holds the lock over PIO + copy; `B_PHYS` user buffers stage through
  a private `kmem_alloc` buffer and drop the lock only for
  `copyin()`/`copyout()`.
- **Open:** CI run `42852193407` (commit `eeb7ddc`) **failed** in the `Build`
  step (7 min). Steps 1–6 and 8–14 succeeded, so patches validated and the IIG
  adapter ran. `xnu-kernel` artifact is 208 KB with only `check_patch.log`,
  `kdk-libs/`, an empty `SHA256SUMS` and the three host tests — no kernel.
  The `xnu-buildtree` artifact contains the patched sources. A local
  `-fsyntax-only` check of `bsd/dev/santoni_sdhci.c` with the exact CI flags is
  clean, and every `.c` in the build tree produced a `.d`, so the failure is
  most likely in a component the local check cannot reproduce faithfully
  (Apple clang 16 vs local clang 23) or in the link stage.

### Next concrete action

1. Add `build.log` to the CI artifacts (or echo its error lines into the job
   summary) and re-run, so a failed build is diagnosable. Do this in the same
   commit as any fix attempt.
2. Fix whatever it reports, then on a green run fetch the kernel via
   nightly.link, confirm `SLIDEFAIL`/`SLIDEMAP` strings are present, rebuild
   with `KERNEL=<new> bash work/build-boot-emmc.sh rw`, `fastboot boot` it.
3. Wait ~210 s, ask the user for Power + Volume Down, boot TWRP, pull
   `mmcblk0p24` (`bs=512 count=8193`), decode with `tools/sweet-log.py`.
4. Success: no `SLIDEFAIL`, no `offset overflow`, no
   `hfs_mark_inconsistent`, and boot past `exec SpringBoard`.
5. Then remove patch `0146` (diagnostic only), commit, and update `NOTES.md`.

## Hardware facts worth keeping

- `PAGE_SIZE` 4 KiB; XNU built with the `SANTONI` machine config (no
  `__ARM_16K_PG__`), 39-bit kernel VA.
- `PHYS_BASE=0x98000000`, `MEM_SIZE=0x28000000` (640 MiB). `phystokv()` panics
  on an illegal PA.
- GICv2 memory-mapped: GICD `0x0b000000`, GICC `0x0b002000`; vtimer INTID 20;
  19.2 MHz timer. Only 1 of 8 CPUs is used so far.
- SDHCI `0x07824900`, GCC `0x01842000`, framebuffer `0x90001000`
  (720×1280 BGR, stride 2160).
- Partitions: `system` = `mmcblk0p24`, `userdata` = `mmcblk0p49`;
  `max-download-size` `0x1ff00000`.
- Dyld slide simulator facts: `delta_mask` `0x00ffff0000000000` (prints as
  `0xffff0000000000`), `delta_shift` 38, `value_mask` `0xff0000ffffffffff`;
  all six slid mappings have zero overflowing pages offline.
