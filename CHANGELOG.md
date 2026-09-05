# Changelog

All notable changes to PHNTM are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows
[SemVer](https://semver.org/).

## [1.6.0] — show it to the world 👻🎞️
**A review section people can trust.** Every screenshot in the README is a real
byte-for-byte terminal capture — regenerated on demand, never mocked.

### Added
- **`brand/screens/` gallery** — 12 screenshots: `help`, `presets`, `components`
  (+ `--direct`), `build --dry-run`, `status` (built stick + clean non-stick refusal),
  `cache`, `doctor`, `--version`, and the 4-screen wizard (persona / tier / plan)
  via Textual's headless `save_screenshot`
- **`tools/screenshots.py`** — one command regenerates everything: CLI shots run in a
  real PTY and replay exact bytes through `pyte`; TUI shots drive `PhntmWizard` headless.
  Requires `pyte` + ImageMagick.
- **README Review section** — the gallery, grouped by workflow, with honest exit codes

### Tests
Full suite still **103 green** (screenshot tooling is a commit-time dev utility,
exercised end-to-end by regenerating the gallery).

## [1.5.0] — known your stick 👻📡
**PHNTM now talks to the stick itself.** `phntm status` and `phntm check` accept a raw
block device (`/dev/sdX`) — PHNTM finds the mounted volume via `lsblk` and reads
`phntm.json` wherever the stick is plugged in. Anything that isn't a PHNTM stick gets
a clear one-liner, never a traceback.

### Added
- **Stick-aware metadata**: `phntm status /dev/sdX` and `phntm check /dev/sdX` work
  (mount folder support kept, of course); missing `phntm.json` → clean error
- **`phntm fetch` keeps going**: one broken component no longer aborts the batch —
  the rest download, every failure is reported, and the command still exits `1`
  (script-friendly)
- **`phntm build` refuses to half-build**: `--no-dry-run` without `--device` now
  errors with a pointer instead of silently degrading to a plan
- **Catalog browsing filters**: `phntm components --kind iso|tool|portable|custom`
  and `--direct` (only components with a download link on record)
- **Real version stamps**: built sticks now record the actual tool version and the
  real catalog version in `phntm.json` (they were placeholders — `1.0.0` /
  hardcoded — before)

### Internal
- dropped dead `require_root()`; metadata reader split (`read_metadata` vs
  `read_metadata_stick`); manifest-error output trimmed to one line

### Tests
`read_metadata_stick` (mount dir, block-device lookup via `lsblk`, clean failure),
CLI status/check/build/fetch/help/components behavior, and a presets data-integrity
suite (all 14 presets validate, resolve against the catalog, fit their tier) —
**103 total**, green on Python 3.11/3.12/3.13.

## [1.4.0] — real build driver 👻🚗
**`phntm build -d /dev/sdX --yes` now does something real.** The Ventoy step is wired:
it detects whether the stick already carries Ventoy (root-free, via partition labels)
and flashes, upgrades, or force-reinstalls accordingly — then halts with a clear note
until the copy layer lands.

### Added
- **Ventoy install driver finished**: native `Ventoy2Disk.sh` or the Docker fallback, idempotent
  - already Ventoy → **upgrade in place** (`-u`, keeps your data partition)
  - already Ventoy + `--force` → reinstall (`-I`)
  - blank stick → fresh install (`-i`)
- **Stick-level Ventoy detection** — `phntm devices` gains a `ventoy` column (installed ✅ / not yet),
  via `lsblk` partition labels, no root needed
- Native Ventoy version shows up in `phntm doctor`
- `phntm fetch` gets **live progress bars** on a terminal (bar + downloaded + transfer speed);
  quiet line mode when piped
- Real-build pipeline tests: concede → ventoy flash → clean halt before the copy layer

### Fixed
- `build` no longer bails on the *first* step — the ventoy step runs for real before the
  not-yet-wired copy layer steps report themselves

### Tests
`test_ventoy.py` grown from 3 → 16 (install/upgrade/force flag selection, lsblk parsing,
failure fallbacks, version sniffing) + new `test_build.py` (real-run pipeline) — **89 total**,
green on Python 3.11/3.12/3.13.

## [1.3.0] — offline arsenal 👻📦
**Offline anything — you can finally get real ISOs onto a stick.** PHNTM now downloads
component files into a local offline cache; builds stay fully offline by design.

### Added
- `phntm fetch <id>… | --all | --manifest <file>` — download components into `~/.cache/phntm`
  - **resume**: an interrupted download keeps a `.part` and continues via HTTP `Range`
  - **verify**: checks sha256 whenever the catalog knows one (mismatch → file rejected, nothing half-written stays behind)
  - `--verify` mode re-checks cached files without touching the network
- `phntm cache` — what's cached, per-component paths, total size
- `phntm doctor` now reports cache status; `phntm build --dry-run` prints exactly which manifest ISOs aren't cached yet
- catalog: 5 ISOs with direct download links on record (kali-linux, hirens-boot-pe, systemrescue, gparted-live, clonezilla-live); the rest stay landing pages you grab by hand
- 13 fetch tests (local HTTP server with Range): happy path, resume, restart-when-Range-ignored, checksum reject, 404, empty, page-only refusal, verify-only, cache listing — **70 total**

## [1.2.0] — tune the plan 👻🔧
**M2 hardened — a real tuning cockpit.** The wizard is now 4 screens.

### Added
- **Components screen (step 3)**: every ISOs/tool becomes a checkbox; uncheck to drop it
- **LUKS persistence toggle** — off by default; flip it to add/remove the encrypted volume
- **Live recompute**: meter, used/total, utilization, and the DROP/VAULT line all react instantly
- **Overflow guard**: uncheck-too-much or oversize plans lock the "Next" button and warn
- 3 new wizard tests (components list, tune-to-metter, persistence toggle) — **57 total**

## [1.1.0] — the wizard 👻✨
**M2 — guided Textual TUI.** Same engine as the CLI, friendlier cockpit.

### Added
- `phntm tui`: 3-screen wizard — persona → tier → plan
  - Persona picker (5 options incl. GENERAL) with curated descriptions
  - Tier picker with per-tier estimated sizes + recommended badge
  - Plan screen: **live size meter** (ProgressBar over usable capacity), full budget breakdown,
    green/red overflow states, plugged-stick hint, manifest save with next-step commands
- Optional `tui` extra (`pip install "phntm[tui]"`); CLI degrades gracefully with an install hint
- 4 headless wizard tests (Textual `run_test` pilot): navigation, meter accuracy, manifest save
- 54 tests total, all green on Python 3.11/3.12/3.13

## [1.0.0] — ghost protocol 👻
First release. **M1 core — fully local, zero telemetry.**

### Added
- Manifest engine v1 (Pydantic): `BuildManifest`, 4 persona × tier presets + GENERAL (16 presets), strict validation
- Component catalog: 26 entries (ISOs, portable tools, PHNTM script layer) with size/url/checksum/release metadata
- Budget engine: usable-capacity model, live utilization, refuse-to-build on overflow, tight-build warning ≥95%
- CLI: `presets`, `components`, `manifest new|validate|show`, `build --dry-run`, `build -d <dev|auto> -y`, `status`, `check`, `update`, `devices`, `doctor`, `test`, `help`
- USB device detection via sysfs: size, USB 2.0/3.0/3.1/3.2 speed, vendor/model, `-d auto` single-stick pick, capacity gate
- Release tracking: every component pins its catalog release; `phntm check` diffs manifest/stick vs catalog (current / update available / vanished)
- Ventoy driver: native or Docker fallback (no-sudo), LUKS persistence plugin config
- Stick identity: `phntm.json` metadata written per build, `file_version` + release pins
- Safety: destructive builds gated on `--yes`; non-removable devices refused; unknown components/manifests rejected loudly
- 50 tests covering manifest, catalog, sizer, CLI, metadata, devices, ventoy, update diff
- MIT license, CI (pytest × python 3.11/3.12/3.13), PyPI release workflow