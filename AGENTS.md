# Working on ios-sweet

- For the lemonadep / HackiOS work, read
  `lemonadep/hackios/FINDINGS-2026-11-01-03.md` first: it is the consolidated record of
  the last 48 hours (GPU/GL split, 120 Hz, Weather, Maps, charging, kernel build) and
  it marks which older claims are stale. `lemonadep/HANDOFF.md` is the recipe.
- Device tests are hands-free and never flash: `lemonadep/hackios/repack-payload.sh`
  repacks `run-payload.bin` from the current `root.apfs`, and
  `lemonadep/hackios/usb-test.sh LOGNAME [SECS]` reuses the loader session, stages,
  runs and fetches its own logs. Do not ask the user to watch the screen or press
  buttons; `kern.bootargs`/`loader_return_after` bound every run.
- Do not pass `USERLAND_VARS=...` to `userland/build.sh` directly — that variable belongs
  to the upstream `common/build.sh` wrapper. Export `GL=1 ADSP=1 ...` yourself, or the
  image silently loses Mesa (a ~18.6 MB `root.apfs` instead of ~25 MB).
- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, CI run IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes. Use `gh` for GitHub Actions kernel builds and logs.
  Local single-file cross-compiles are useful before spending a CI run.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. The user approved (2026-10-15) using
  internal UFS for iOS and said Android may be deleted: the iOS root goes
  into the existing `userdata` partition (no GPT changes). Keep bootloaders,
  recovery, modem, persist and the backups intact, and confirm each
  destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.
