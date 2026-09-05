# Contributing to PHNTM

PHNTM is an open, community-driven project. Every contribution is welcome:
bug reports, catalog additions, preset tuning, docs, new personas.

## Quick start

```bash
git clone https://github.com/merouanebenboucherit-cmd/phntm.git
cd phntm
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # all tests must pass
```

## Adding a component to the catalog

1. Edit `phntm/data/catalog.json`.
2. Every entry needs: unique slug `id`, `name`, `kind`, `categories`, `persona_tags`,
   real `size_gb`, download `url`, and ideally `sha256` + `release` (version string).
3. If it belongs on a shipped preset, add it to `phntm/data/presets.json`.
4. Run tests — `test_catalog` verifies every preset references only existing ids, and
   `test_sizer` asserts every shipped preset still fits its tier.
5. If a preset no longer fits, adjust sizes or swap items — don't silently break the budget.

## Conventions

- Python 3.11+, type hints everywhere, pydantic models for all data.
- No telemetry, no network calls at runtime unless the user runs an update command.
- CLI commands live in `phntm/cli.py`; logic lives in `phntm/engine/`; tests stay hermetic
  (inject fake sysfs/roots — never touch real devices in tests).
- Every new command/behavior gets a CLI smoke test.

## Commit & PR

- Prefer focused commits; message like `catalog: add foo-2026.1` or `sizer: warn at 95%`.
- CI runs pytest on 3.11/3.12/3.13 for every PR — make it green before requesting review.

## Releasing (maintainers)

Version bumps are SemVer, tagged `vX.Y.Z`. On tag, CI builds and publishes to PyPI
(requires the `PYPI_API_TOKEN` secret). Update `CHANGELOG.md` in the same release commit.