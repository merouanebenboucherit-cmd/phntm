# Changelog

All notable changes to PHNTM are tracked here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning follows
[SemVer](https://semver.org/).

## [Unreleased]
- M2: Textual TUI wizard with live size meter
- M3: hardware drivers — real Ventoy build, LUKS persistence, QEMU boot-test
- M4: catalog auto-refresh (`phntm update`), offline bundles, `phntm upgrade`

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