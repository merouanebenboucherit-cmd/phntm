"""Ventoy driver tests — mocked subprocesses, no real hardware."""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from phntm.engine.build import BuildError
from phntm.engine.ventoy import (
    VENTOY_DOCKER_IMAGE,
    VentoyTool,
    install_ventoy,
    ventoy_json,
)


def test_detect_modes_are_sane():
    tool = VentoyTool.detect()
    assert tool.mode in ("native", "docker", "none")
    if tool.mode == "native":
        assert shutil.which("Ventoy2Disk.sh") or shutil.which("ventoy")
    elif tool.mode == "docker":
        assert shutil.which("docker")


def test_ventoy_json_has_persistence_plugin():
    cfg = ventoy_json(theme="minimal-dark")
    assert cfg["theme"]["file"] == "/ventoy/theme/minimal-dark/theme.txt"
    assert cfg["persistence"][0]["image"] == "/ISOS/kali-linux-*.iso"


def test_ventoy_json_without_theme_has_no_theme_key():
    cfg = ventoy_json()
    assert "theme" not in cfg
    assert "persistence" in cfg


# --------------------------------------------------------------------------- install commands

def test_native_install_cmd():
    tool = VentoyTool(mode="native")
    cmd = tool.install_cmd("/dev/sdb")
    assert cmd[0] in ("Ventoy2Disk.sh", "ventoy")
    assert "-i" in cmd and "/dev/sdb" in cmd


def test_native_force_flag():
    tool = VentoyTool(mode="native")
    assert "-I" in tool.install_cmd("/dev/sdb", force=True)


def test_native_upgrade_flag():
    tool = VentoyTool(mode="native")
    assert "-u" in tool.install_cmd("/dev/sdb", upgrade=True)


def test_docker_install_cmd():
    tool = VentoyTool(mode="docker")
    cmd = tool.install_cmd("/dev/sdc")
    assert cmd[:2] == ["docker", "run"]
    assert "--privileged" in cmd
    assert "-v", "/dev:/dev:rw" in [tuple(cmd[i : i + 2]) for i in range(len(cmd))]
    assert VENTOY_DOCKER_IMAGE in cmd
    assert "-i" in cmd and "/dev/sdc" in cmd


# --------------------------------------------------------------------------- installed_on

def test_installed_on_detects_ventoy_labels(monkeypatch):
    def fake_lsblk(*args, **kwargs):
        return "VTOYEFI\nVentoy\n"
    monkeypatch.setattr("phntm.engine.ventoy.subprocess.check_output", fake_lsblk)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/lsblk" if name == "lsblk" else None)
    assert VentoyTool(mode="native").installed_on("/dev/sdx9")


def test_installed_on_false_for_plain_stick(monkeypatch):
    def fake_lsblk(*args, **kwargs):
        return "DELL_STICK\n"
    monkeypatch.setattr("phntm.engine.ventoy.subprocess.check_output", fake_lsblk)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/lsblk" if name == "lsblk" else None)
    assert not VentoyTool(mode="native").installed_on("/dev/sdx9")


def test_installed_on_missing_lsblk(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert not VentoyTool(mode="native").installed_on("/dev/sdx9")


def test_installed_on_failure_is_false(monkeypatch):
    import subprocess

    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(2, "lsblk")
    monkeypatch.setattr("phntm.engine.ventoy.subprocess.check_output", boom)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/lsblk" if name == "lsblk" else None)
    assert not VentoyTool(mode="native").installed_on("/dev/sdx9")


# --------------------------------------------------------------------------- install_ventoy flow

def test_install_ventoy_plain_install(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(VentoyTool, "detect", classmethod(lambda cls: VentoyTool(mode="native")))
    monkeypatch.setattr(VentoyTool, "installed_on", lambda self, dev: False)

    def fake_run(self, device, *, force=False, upgrade=False, dry_run=False):
        calls.append((device, force, upgrade, dry_run))
        return []

    monkeypatch.setattr(VentoyTool, "run", fake_run)
    install_ventoy("/dev/sdx9")
    assert calls == [("/dev/sdx9", False, False, False)]


def test_install_ventoy_upgrades_when_present(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(VentoyTool, "detect", classmethod(lambda cls: VentoyTool(mode="native")))
    monkeypatch.setattr(VentoyTool, "installed_on", lambda self, dev: True)

    def fake_run(self, device, *, force=False, upgrade=False, dry_run=False):
        calls.append((device, force, upgrade, dry_run))
        return []

    monkeypatch.setattr(VentoyTool, "run", fake_run)
    install_ventoy("/dev/sdx9")
    assert calls == [("/dev/sdx9", False, True, False)]  # upgrade selected


def test_install_ventoy_force_reinstall_when_present(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(VentoyTool, "detect", classmethod(lambda cls: VentoyTool(mode="native")))
    monkeypatch.setattr(VentoyTool, "installed_on", lambda self, dev: True)

    def fake_run(self, device, *, force=False, upgrade=False, dry_run=False):
        calls.append((device, force, upgrade, dry_run))
        return []

    monkeypatch.setattr(VentoyTool, "run", fake_run)
    install_ventoy("/dev/sdx9", force=True)
    assert calls == [("/dev/sdx9", True, False, False)]  # force, no upgrade


def test_install_ventoy_no_tool_raises(monkeypatch):
    monkeypatch.setattr(VentoyTool, "detect", classmethod(lambda cls: VentoyTool(mode="none")))
    with pytest.raises(BuildError, match="Cannot install Ventoy"):
        install_ventoy("/dev/sdx9")


# --------------------------------------------------------------------------- version

def test_native_version_parsed(monkeypatch):
    monkeypatch.setattr(
        "phntm.engine.ventoy.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout="Ventoy2Disk.sh 1.0.99\n", stderr=""),
    )
    assert VentoyTool(mode="native").version() == "Ventoy2Disk.sh 1.0.99"


def test_docker_version_is_none():
    assert VentoyTool(mode="docker").version() is None


def test_version_survives_failure(monkeypatch):
    import subprocess

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired("Ventoy2Disk.sh", 10)
    monkeypatch.setattr("phntm.engine.ventoy.subprocess.run", boom)
    assert VentoyTool(mode="native").version() is None