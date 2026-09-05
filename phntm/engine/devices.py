"""Removable-device discovery via sysfs — local, no privileges, no writing.

Pure functions with an injectable sysfs root so the whole thing is testable
against a fake tree (no real USB needed).

Where the facts come from (Linux):
  /sys/block/sdX/removable        1 = removable drive (USB sticks, card readers)
  /sys/block/sdX/size             512-byte sector count
  /sys/block/sdX/device/vendor    scsi-reported vendor (often empty for USB)
  USB speed: walk up the sysfs parent chain to the first dir with a `speed`
  file (e.g. /sys/bus/usb/devices/1-1/speed = 480 | 5000 | 10000 | 20000 Mbps)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Negotiated USB speed (Mbps) -> marketing version.
USB_SPEED_LABELS = {
    480: "2.0",
    5000: "3.0",
    10000: "3.1",
    20000: "3.2",
}


@dataclass
class UsbInfo:
    speed: int | None = None
    vendor: str | None = None
    product: str | None = None
    serial: str | None = None

    @property
    def speed_label(self) -> str:
        if self.speed is None:
            return "unknown"
        return USB_SPEED_LABELS.get(self.speed, f"{self.speed // 1000}Gbps (legacy)")


@dataclass
class BlockDevice:
    name: str            # e.g. "sda"
    path: str            # e.g. "/dev/sda"
    size_bytes: int
    removable: bool
    model: str | None = None
    vendor: str | None = None
    usb: UsbInfo | None = None

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1_000_000_000

    def human_size(self) -> str:
        gb = self.size_gb
        if gb >= 1000:
            return f"{gb / 1000:.1f} TB"
        return f"{gb:.0f} GB"

    def fits(self, needed_gb: float, safety_gb: float = 1.0) -> bool:
        """Can this stick hold a build that needs `needed_gb` of payload?"""
        return self.size_gb >= needed_gb + safety_gb


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, ValueError):
        return None


def _sysfs_usb_info(block_root: Path) -> UsbInfo | None:
    """Walk up from /sys/devices/.../block/sdX to the USB device dir."""
    node = block_root.parent  # .../block
    while node != node.parent:
        speed = _read(node / "speed")
        if speed is not None:
            try:
                speed_int = int(speed) if speed.isdigit() else None
            except ValueError:
                speed_int = None
            return UsbInfo(
                speed=speed_int,
                vendor=_read(node / "manufacturer") or _read(node / "idVendor"),
                product=_read(node / "product") or None,
                serial=_read(node / "serial") or None,
            )
        node = node.parent
    return None


def scan_devices(sysfs_root: str = "/sys", dev_root: str = "/dev") -> list[BlockDevice]:
    """Return removable whole-disk block devices (sdX only). No USB? Empty list."""
    block_dir = Path(sysfs_root) / "block"
    if not block_dir.is_dir():
        return []
    found: list[BlockDevice] = []
    for entry in sorted(block_dir.glob("sd[a-z]")):
        removable_raw = _read(entry / "removable")
        size_raw = _read(entry / "size")
        if removable_raw != "1" or not size_raw:
            continue
        try:
            sectors = int(size_raw)
        except ValueError:
            continue
        device_sym = entry / "device"
        model = None
        if device_sym.exists():
            target = device_sym.resolve()
            model = _read(target / "model") if target.is_dir() else None
        usb = _sysfs_usb_info(entry)
        found.append(
            BlockDevice(
                name=entry.name,
                path=os.path.join(dev_root, entry.name),
                size_bytes=sectors * 512,
                removable=True,
                model=model,
                vendor=usb.vendor if usb else None,
                usb=usb,
            )
        )
    return found


def resolve_device(
    device_arg: str,
    *,
    sysfs_root: str = "/sys",
    dev_root: str = "/dev",
) -> str:
    """Resolve --device. 'auto' picks a single stick; explicit paths pass through."""
    if device_arg not in ("auto", ""):
        return device_arg
    sticks = scan_devices(sysfs_root, dev_root)
    if len(sticks) == 1:
        return sticks[0].path
    if not sticks:
        raise LookupError("no removable USB stick detected — plug one in, or pass --device /dev/sdX")
    listing = ", ".join(s.path for s in sticks)
    raise LookupError(f"{len(sticks)} sticks detected — be explicit: --device {'|'.join(s.path for s in sticks)}")


def device_capacity(device: str, *, sysfs_root: str = "/sys") -> float:
    """Real capacity of a block device path in GB (0 if unknown/not found)."""
    name = os.path.basename(device)
    size_raw = _read(Path(sysfs_root) / "block" / name / "size")
    if not size_raw:
        return 0.0
    try:
        return int(size_raw) * 512 / 1_000_000_000
    except ValueError:
        return 0.0