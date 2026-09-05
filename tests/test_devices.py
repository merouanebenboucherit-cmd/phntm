"""Removable-device discovery against a fake sysfs tree — no USB needed."""

import os

from phntm.engine.devices import (
    BlockDevice,
    scan_devices,
    resolve_device,
    device_capacity,
)


def fake_sysfs(tmp_path):
    """Build a fake sysfs layout with one 32GB USB3 stick and one non-removable disk."""
    block = tmp_path / "block"
    (block / "sda").mkdir(parents=True)
    (block / "sda" / "removable").write_text("1")
    (block / "sda" / "size").write_text("62521344")  # ×512 = 32,010,928,128 B ≈ 32 GB

    (block / "sdb").mkdir()
    (block / "sdb" / "removable").write_text("0")
    (block / "sdb" / "size").write_text("62521344")

    # Emulate the USB parent chain discovered by walking up from block/.
    (tmp_path / "speed").write_text("5000")
    (tmp_path / "manufacturer").write_text("SanDisk")
    (tmp_path / "product").write_text("iXpand Ultra")
    (tmp_path / "serial").write_text("4C5300")

    # /sys/block/sda/device -> somewhere with a model file.
    (tmp_path / "device" / "zzz").mkdir(parents=True)
    (tmp_path / "device" / "zzz" / "model").write_text("USB 3.0")
    (block / "sda" / "device").symlink_to(tmp_path / "device" / "zzz")
    (block / "sdb" / "device").symlink_to(tmp_path / "device" / "zzz")
    return tmp_path


def test_scan_finds_only_removable_stick(tmp_path):
    root = fake_sysfs(tmp_path)
    sticks = scan_devices(sysfs_root=str(root), dev_root="/dev")
    assert [s.name for s in sticks] == ["sda"]  # sdb is removable=0 → excluded


def test_device_facts_are_correct(tmp_path):
    root = fake_sysfs(tmp_path)
    (s,) = scan_devices(sysfs_root=str(root), dev_root="/dev")
    assert s.path == "/dev/sda"
    assert s.size_gb == 32.010928128
    assert "32 GB" in s.human_size()
    assert s.usb is not None
    assert s.usb.speed == 5000
    assert s.usb.speed_label == "3.0"
    assert s.model == "USB 3.0"
    assert s.usb.vendor == "SanDisk"
    assert s.usb.serial == "4C5300"


def test_fits_accounts_for_safety_margin(tmp_path):
    root = fake_sysfs(tmp_path)
    (s,) = scan_devices(sysfs_root=str(root), dev_root="/dev")
    assert s.fits(27.6)          # 32.01 >= 27.6 + 1.0
    assert not s.fits(31.5)      # 32.01 < 31.5 + 1.0


def test_resolve_device_auto_picks_single_stick(tmp_path):
    root = fake_sysfs(tmp_path)
    assert resolve_device("auto", sysfs_root=str(root), dev_root="/dev") == "/dev/sda"


def test_resolve_device_auto_fails_without_sticks(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    try:
        resolve_device("auto", sysfs_root=str(empty), dev_root="/dev")
        raise AssertionError("expected LookupError for no sticks")
    except LookupError as exc:
        assert "no removable USB stick" in str(exc)


def test_device_capacity_reads_sectors(tmp_path):
    root = fake_sysfs(tmp_path)
    assert device_capacity("/dev/sda", sysfs_root=str(root)) == 32.010928128
    assert device_capacity("/dev/nonexistent", sysfs_root=str(root)) == 0.0