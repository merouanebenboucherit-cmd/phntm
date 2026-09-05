"""Real-build pipeline tests — the ventoy step now actually flashes."""

from __future__ import annotations

import pytest

from phntm.catalog import load_catalog
from phntm.engine import build as build_mod
from phntm.models import Persona
from phntm.presets import manifest_from_preset


def _manifest():
    return manifest_from_preset(Persona.PENTEST, 32)


def test_run_build_flashes_ventoy_then_halts_at_partition(monkeypatch):
    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    flashed: list[str] = []
    monkeypatch.setattr(build_mod, "_ventoy_driver", lambda dev: (lambda: flashed.append(dev)))
    with pytest.raises(build_mod.BuildError, match="partition"):
        build_mod.run_build(_manifest(), load_catalog(), "/dev/sdx9", yes=True)
    assert flashed == ["/dev/sdx9"]  # ventoy driver ran exactly once, with the right device


def test_run_build_requires_yes(monkeypatch):
    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    with pytest.raises(build_mod.BuildError, match="requires --yes"):
        build_mod.run_build(_manifest(), load_catalog(), "/dev/sdx9", yes=False)


def test_run_build_refuses_non_removable(monkeypatch, tmp_path):
    # fake /sys tree: /dev/sdz1 exists as a file but sysfs says removable=0
    fake_sys = tmp_path / "sys"
    (fake_sys / "block" / "sdz1" / "removable").parent.mkdir(parents=True)
    (fake_sys / "block" / "sdz1" / "removable").write_text("0")
    dev = tmp_path / "sdz1"
    dev.write_text("")
    monkeypatch.setattr(build_mod, "_ventoy_driver", lambda d: (lambda: None))
    with pytest.raises(build_mod.BuildError, match="not a removable device"):
        build_mod.run_build(_manifest(), load_catalog(), str(dev), yes=True, sysfs_root=str(fake_sys))


def test_ventoy_step_is_attached_to_plan():
    plan = str(build_mod.dry_run(_manifest(), load_catalog()))
    assert "Install Ventoy" in plan