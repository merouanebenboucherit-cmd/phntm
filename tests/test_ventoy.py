"""Ventoy driver detection — no sudo, docker fallback, honest failure."""

import shutil

from phntm.engine.ventoy import VentoyTool, ventoy_json


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