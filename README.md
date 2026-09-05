# 👻 PHNTM

<p align="center">
  <img src="brand/phntm-logo.svg" alt="PHNTM — Ghost USB logo" width="320"/>
</p>

<p align="center">
  <img src="https://github.com/merouanebenboucherit-cmd/phntm/actions/workflows/ci.yml/badge.svg" alt="CI"/>&nbsp;
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"/>&nbsp;
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+"/>&nbsp;
  <img src="https://img.shields.io/badge/tests-103%20passing-brightgreen" alt="tests: 103 passing"/>
</p>

**Build legendary USB sticks.** IT Tech, Pentester, DFIR, Privacy — pick a persona, pick a size, get a battle-tested bootable stick.

**Local-first. Open source (MIT). Zero telemetry. No host. No cloud.**

### What it is

PHNTM turns a plain USB drive into a **bootable "ghost stick"**: a battle-ready, fully
offline arsenal built on [Ventoy](https://www.ventoy.net/) — live ISOs, portable tools,
an encrypted vault, and per-OS persistence volumes — assembled from validated plans that
physically fit the stick, no internet required after you prepare it.

### What it's for

Exactly one goal: when a machine dies, gets compromised, or needs rebuilding, you have a
stick you **made ahead of time**. Boot it, rescue data, reinstall, wipe, run forensics —
with no internet, no cloud, and no double-clicking random downloads mid-emergency.
The toolchain itself is 100% local: presets → tuned plan → offline ISO cache → real stick.

```
   persona × tier                    ┌─ 16 GB  GHOST    (lean, essentials)
   IT / PENTEST / DFIR / PRIVACY ────┤─ 32 GB  SPECTRE  (standard, workhorse)
   + GENERAL mix                     └─ 64 GB  PHANTOM  (full arsenal)
                                       (+128 GB BANSHEE for GENERAL)
```

## Concept

concept art of the PHNTM idea — originals in `brand/*-ai.png`:

<p align="center">
  <img src="brand/phntm-hero-ai-web.png" alt="PHNTM hero concept — personas into tiers into a legendary stick" width="820"/>
</p>

<p align="center">
  <img src="brand/phntm-logo-ai-web.png" alt="PHNTM Ghost USB logo concept" width="320"/>
</p>

---

## The wizard ✨

`phntm tui` — a guided, keyboard-first wizard that turns a persona + a stick size
into a validated build plan you can **tune**, with a **live size meter** that refuses
plans which physically won't fit:

| Pick a persona | Tune the components | Preview the plan |
|:---:|:---:|:---:|
| <img src="brand/screens/raw-tui-persona.png" alt="Step 1 — choose a persona" width="330"/> | <img src="brand/screens/raw-tui-components.png" alt="Step 3 — tune components + live meter" width="330"/> | <img src="brand/screens/raw-tui-plan.png" alt="Step 4 — live size meter" width="330"/> |

```
persona → tier → tune → save   uncheck an ISO/tool or toggle LUKS persistence and
                               the meter reacts live. Every screen is the same
                               engine the CLI uses, so a saved manifest ==
                               `phntm manifest new`
```

## Review — real screenshots

Every shot below is a **live byte-for-byte capture** of the actual CLI (through a real
terminal) and the actual TUI (Textual headless), not mocked mockups. Regenerate anytime
with `python tools/screenshots.py` (requires `pyte` + ImageMagick).

### Plan & tune
| `phntm help` — the whole workflow on one screen | `phntm presets` — 14 planned persona × tier builds |
|:---:|:---:|
| <img src="brand/screens/cli-help.png" alt="phntm help" width="400"/> | <img src="brand/screens/cli-presets.png" alt="phntm presets" width="400"/> |

### Browse the arsenal
| `phntm components` — search the 25-component catalog | `phntm components --direct` — only download-ready ISOs |
|:---:|:---:|
| <img src="brand/screens/cli-components.png" alt="phntm components" width="400"/> | <img src="brand/screens/cli-components-direct.png" alt="phntm components --direct" width="400"/> |

### Build plan (zero side effects)
| `phntm build --dry-run` — full plan, budget, steps, cache checks |
|:---:|
| <img src="brand/screens/cli-manifest-plan.png" alt="phntm build --dry-run" width="460"/> |

### Status & cache
| `phntm status` on a built stick | `phntm cache` — the offline arsenal |
|:---:|:---:|
| <img src="brand/screens/cli-status-stick.png" alt="phntm status" width="400"/> | <img src="brand/screens/cli-cache.png" alt="phntm cache" width="400"/> |

### The wizard (TUI)
| Step 1 — persona | Step 2 — tier | Step 3 — tune components + live meter | Step 4 — plan & save |
|:---:|:---:|:---:|:---:|
| <img src="brand/screens/raw-tui-persona.png" alt="wizard — persona" width="315"/> | <img src="brand/screens/raw-tui-tier.png" alt="wizard — tier" width="315"/> | <img src="brand/screens/raw-tui-components.png" alt="wizard — components" width="315"/> | <img src="brand/screens/raw-tui-plan.png" alt="wizard — plan" width="315"/> |

### Health & version
| `phntm doctor` — build-ready? | `phntm --version` |
|:---:|:---:|
| <img src="brand/screens/cli-doctor.png" alt="phntm doctor" width="460"/> | <img src="brand/screens/cli-version.png" alt="phntm --version" width="200"/> |

## Why PHNTM

- **Manifests, not magic** — every stick is a validated `BuildManifest` (v1). The same file drives building, status, and updates.
- **The size engine** — PHNTM computes the real budget (ISOs + persistence + vault + drop) against the stick's usable capacity and *refuses lies*.
- **sha256 everywhere** — nothing lands on a stick unverified.
- **No-sudo flashing** — Ventoy native **or** Docker fallback. Works on this very workstation.
   |`phntm devices` reads size, USB 2.0/3.0/3.1/3.2 speed, vendor/model straight from sysfs, plus Ventoy install state; `build -d auto` picks the single plugged stick and refuses sticks that physically can't hold the plan.
- **Your stick, your rules** — encrypted VAULT (cryptsetup/LUKS), LUKS persistence for Kali, DROP scratch folder. Nothing auto-runs. No phoning home.

## Install

```bash
# from the repo (recommended for now)
git clone https://github.com/merouanebenboucherit-cmd/phntm.git
cd phntm
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,tui]"
alias phntm="$HOME/phntm/.venv/bin/phntm"   # or add .venv/bin to PATH

# once published to PyPI:
pip install "phntm[tui]"
```

## Quickstart

```bash
phntm tui                                            # ✨ the wizard: persona → tier → plan
phntm devices                                        # detect stick: size + USB + Ventoy state
phntm presets                                        # browse personas × tiers
phntm doctor                                         # is this machine build-ready?
phntm fetch --all                                    # 🛰 grab ISOs into ~/.cache/phntm (resumable, sha256-verified)

phntm build build.json --dry-run                     # full plan, zero side effects (shows what's not cached yet)
phntm build build.json -d auto -y                    # real build, auto-picks the single stick
phntm status /media/USB                              # what's on the stick (mount folder, or /dev/sdX)
phntm check build.json                               # fresh vs catalog? (stick or manifest)
phntm cache                                          # what's sitting in the offline cache
phntm update                                         # catalog status
```

## Commands

| Command | What it does |
|---|---|
| `phntm tui` | **guided wizard** — persona → tier → tune components → live-meter plan |
| `phntm devices` | detect plugged-in sticks: size, USB speed, vendor/model, Ventoy state |
| `phntm presets` | persona × tier matrix — 14 presets with estimated sizes |
| `phntm components [kw]` | browse the catalog (`--persona`, `--category`, `--kind`, `--direct`) |
| `phntm manifest new -p <persona> -t <tier> -o f.json` | create a build manifest |
| `phntm manifest validate -f f.json` | sanity + fits-on-stick check |
| `phntm build f.json --dry-run` | full plan, zero side effects |
| `phntm build f.json -d auto -y` | real build — flashes Ventoy for real (smart upgrade), halts before the copy layer |
| `phntm status /media/USB` | what a PHNTM stick contains (or `phntm status /dev/sdX` — PHNTM finds its volume) |
| `phntm check <manifest-or-stick>` | freshness diff vs catalog |
| `phntm update` | catalog status |
| `phntm doctor` | is this machine ready to build sticks? |
| `phntm fetch <id>… / --all / -m f.json` | download ISOs into `~/.cache/phntm` — resumable, sha256-checked, keeps going if one component fails |
| `phntm cache` | what's cached, and how much space it takes |

## Anatomy of a built stick

```
VENTOY          bootloader  (any FAT/EXFAT/NTFS/x86 ISO boots)
 ISOS/          live ISOs + Windows installation media (Ventoy boots them)
 TOOLS/         portable tools incl. PHNTM script layer (router creds, disk info…)
 DROP/          plaintext scratch space you control
 VAULT/         encrypted volume (cryptsetup) — your secrets, your key
 PERSIST/       LUKS persistence volumes for per-OS state (e.g. Kali)
 phntm.json     machine-readable metadata: version, build date, component pins
```

## Status

`1.6.0`

- **Core ✅** manifest engine, catalog (25 components), 14 presets, budget engine, device detection, CLI
- **Wizard ✅** Textual TUI — persona → tier → tune components + live size meter
- **Fetch ✅** `phntm fetch` — real ISOs into an offline cache, resumable + sha256-verified
- **Build driver ✅** `phntm build … --yes` flashes Ventoy for real (upgrades smartly when the stick already has it)
- **Stick-aware status ✅** `phntm status /dev/sdX` — block devices work, non-sticks get a clean one-liner
- **Review ✅** real screenshot gallery (PTY/TUI captures, `tools/screenshots.py` regenerates) — 103 tests

follow for more

## Project files

- [CHANGELOG.md](CHANGELOG.md) — release history
- [CONTRIBUTING.md](CONTRIBUTING.md) — add catalog entries, run tests, PR flow
- [SECURITY.md](SECURITY.md) — how to report vulnerabilities privately
- [LICENSE](LICENSE) — MIT

## License

MIT. Fork it, build on it — keep the crediting line.