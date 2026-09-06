"""Real-build pipeline tests — ventoy flashes, the data partition is staged."""

from __future__ import annotations

import pytest

from phntm.catalog import load_catalog
from phntm.engine import build as build_mod
from phntm.models import Persona
from phntm.presets import manifest_from_preset


def _manifest():
    return manifest_from_preset(Persona.PENTEST, 32)


EXPECTED_PARTS = ["isos", "tools", "setup", "persist", "vault", "drop", "theme"]


def test_run_build_flashes_ventoy_then_stages_every_part(monkeypatch, tmp_path):
    stick = tmp_path / "stick"
    stick.mkdir()
    flashed: list[str] = []
    calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    monkeypatch.setattr(
        build_mod, "_ventoy_driver", lambda dev: (lambda: flashed.append(dev))
    )
    monkeypatch.setattr(
        build_mod, "mount_root_for", lambda dev, timeout=30.0, interval=1.0: stick
    )

    def fake_copy(manifest, catalog, mount_root, *, parts, report, verify, cache):
        calls.append((str(mount_root), tuple(parts)))
        return report

    monkeypatch.setattr(build_mod, "run_copy_layer", fake_copy)

    meta, report = build_mod.run_build(
        _manifest(), load_catalog(), "/dev/sdx9", yes=True, cache=str(tmp_path / "cache")
    )

    # Ventoy ran exactly once, with the right device.
    assert flashed == ["/dev/sdx9"]
    # Every staged part drove the copy layer, in plan order, against the stick.
    assert [c[0] for c in calls] == [str(stick)] * len(EXPECTED_PARTS)
    assert [c[1] for c in calls] == [(p,) for p in EXPECTED_PARTS]
    # Metadata written by the build itself, stick-side.
    assert (stick / "phntm.json").exists()
    assert report.mount_root == stick
    assert report.ok
    assert meta.name == _manifest().name


def test_run_build_fails_loudly_when_partition_never_mounts(monkeypatch):
    flashed: list[str] = []
    ran_copy: list[str] = []

    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    monkeypatch.setattr(
        build_mod, "_ventoy_driver", lambda dev: (lambda: flashed.append(dev))
    )
    monkeypatch.setattr(
        build_mod, "mount_root_for", lambda dev, timeout=30.0, interval=1.0: None
    )

    def fake_copy(*a, **kw):
        ran_copy.append("called")

    monkeypatch.setattr(build_mod, "run_copy_layer", fake_copy)

    with pytest.raises(build_mod.BuildError, match="never mounted"):
        build_mod.run_build(_manifest(), load_catalog(), "/dev/sdx9", yes=True)

    assert flashed == ["/dev/sdx9"]
    assert ran_copy == []  # nothing staged without a mount root


def test_run_build_falls_back_to_mount_hint(monkeypatch, tmp_path):
    """--mount <dir> is honored when auto-mount fails but the user mounted it."""
    hint = tmp_path / "mounted-stick"
    hint.mkdir()
    calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    monkeypatch.setattr(build_mod, "_ventoy_driver", lambda dev: (lambda: None))
    monkeypatch.setattr(
        build_mod, "mount_root_for", lambda dev, timeout=30.0, interval=1.0: None
    )

    def fake_copy(manifest, catalog, mount_root, *, parts, report, verify, cache):
        calls.append((str(mount_root), tuple(parts)))
        return report

    monkeypatch.setattr(build_mod, "run_copy_layer", fake_copy)

    meta, report = build_mod.run_build(
        _manifest(), load_catalog(), "/dev/sdx9", yes=True, mount_hint=hint
    )

    assert report.mount_root == hint
    assert [c[0] for c in calls] == [str(hint)] * len(EXPECTED_PARTS)
    assert (hint / "phntm.json").exists()


def test_run_build_ignores_mount_hint_when_auto_mount_worked(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    hint = tmp_path / "hint"
    hint.mkdir()
    calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(build_mod, "_device_ok", lambda d, s="/sys": None)
    monkeypatch.setattr(build_mod, "_ventoy_driver", lambda dev: (lambda: None))
    monkeypatch.setattr(
        build_mod, "mount_root_for", lambda dev, timeout=30.0, interval=1.0: real
    )

    def fake_copy(manifest, catalog, mount_root, *, parts, report, verify, cache):
        calls.append((str(mount_root), tuple(parts)))
        return report

    monkeypatch.setattr(build_mod, "run_copy_layer", fake_copy)

    build_mod.run_build(_manifest(), load_catalog(), "/dev/sdx9", yes=True, mount_hint=hint)

    assert [c[0] for c in calls] == [str(real)] * len(EXPECTED_PARTS)
    assert (real / "phntm.json").exists()


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


def test_mount_and_copy_steps_are_attached_to_plan():
    plan = str(build_mod.dry_run(_manifest(), load_catalog()))
    assert "Mount the exFAT data partition" in plan
    assert "Stage ISOs" in plan
    assert "Write SETUP/" in plan
    assert "LUKS persistence" in plan
    assert "VAULT container" in plan
    assert "DROP scratch" in plan