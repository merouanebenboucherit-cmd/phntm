"""Ventoy install driver — native tool when present, Docker fallback otherwise.

PHNTM works without sudo: Ventoy itself is unprivileged (it submits the disk
ioctl via its own helpers), and the Docker fallback runs the official Ventoy
image with --privileged for those without the binary.

Version flags used (Ventoy2Disk.sh / docker entrypoint):
  -i   install (format + full layout)
  -I   force reinstall (when a Ventoy install is already detected)
  -u   upgrade in place (keeps the data partition)

Ventoy presences is detected root-free via `lsblk -o LABEL`:
partition 2 carries the `VTOYEFI` label and the data partition defaults to
`Ventoy`; either marker means the stick is already flashing-ready.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .build import BuildError, tool_is_on_path

# Community-maintained image; overridable via env for air-gapped/verified use.
VENTOY_DOCKER_IMAGE = os.environ.get("PHNTM_VENTOY_IMAGE", "ventoy/ventoy:latest")

# Root-free markers for "this device already has Ventoy on it".
VENTOY_LABEL_MARKERS = {"VENTOY", "VTOYEFI", "VTOY"}


@dataclass
class VentoyTool:
    mode: str  # "native" | "docker" | "none"

    @classmethod
    def detect(cls) -> "VentoyTool":
        for name in ("Ventoy2Disk.sh", "ventoy", "Ventoy2Disk"):
            if tool_is_on_path(name):
                return cls(mode="native")
        if tool_is_on_path("docker"):
            return cls(mode="docker")
        return cls(mode="none")

    @property
    def binary(self) -> str | None:
        return shutil.which("Ventoy2Disk.sh") or shutil.which("ventoy")

    @property
    def message(self) -> str:
        if self.mode == "native":
            version = self.version()
            return f"ventoy detected on PATH{f' ({version})' if version else ''}"
        if self.mode == "docker":
            return f"no native ventoy; using docker image {VENTOY_DOCKER_IMAGE}"
        return "NEITHER ventoy NOR docker — install packages ventoy or docker first"

    def version(self) -> str | None:
        """Best-effort version string; None when the binary can't answer."""
        if self.mode != "native":
            return None
        try:
            out = subprocess.run(
                [self.binary or "Ventoy2Disk.sh", "-v"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None

    def install_cmd(self, device: str, *, force: bool = False, upgrade: bool = False) -> list[str]:
        """Exact argv for this mode — exposed so callers can show or test it."""
        flag = "-u" if upgrade else ("-I" if force else "-i")
        if self.mode == "native":
            return [self.binary or "Ventoy2Disk.sh", flag, device]
        return [
            "docker", "run", "--rm", "--privileged",
            "-v", "/dev:/dev:rw",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            VENTOY_DOCKER_IMAGE, flag, device,
        ]

    def run(self, device: str, *, force: bool = False, upgrade: bool = False, dry_run: bool = False) -> list[str]:
        """Execute the install/upgrade; returns the argv it used."""
        cmd = self.install_cmd(device, force=force, upgrade=upgrade)
        if dry_run:
            print(f"  ventoy {self.mode} (dry-run): {' '.join(cmd[:6])} … {device}")
            return cmd
        preview = " ".join(cmd[:6]).replace(device, "…")
        print(f"  ventoy {self.mode}: {preview} {device}  [{'upgrade' if upgrade else 'install'}]")
        subprocess.run(cmd, check=True)
        return cmd

    def installed_on(self, device: str) -> bool:
        """Root-free check: does the device already carry Ventoy partitions?"""
        if not shutil.which("lsblk"):
            return False  # can't tell — caller falls back to plain install
        try:
            out = subprocess.check_output(
                ["lsblk", "-n", "-o", "LABEL", device],
                stderr=subprocess.DEVNULL, text=True, timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
        labels = {line.strip().upper() for line in out.splitlines() if line.strip()}
        return bool(labels & VENTOY_LABEL_MARKERS)


def install_ventoy(device: str, *, force: bool = False, dry_run: bool = False) -> None:
    """Flash Ventoy onto the device — idempotent: upgrades when already present."""
    tool = VentoyTool.detect()
    if tool.mode == "none":
        raise BuildError(f"Cannot install Ventoy: {tool.message}. Aborting before touching {device}.")

    already = tool.installed_on(device)
    action = "upgrade" if (already and not force) else ("force-reinstall" if already else "install")
    print(f"  ventoy on {device}: {'detected — ' + action if already else 'fresh install'}")
    tool.run(device, force=force, upgrade=already and not force, dry_run=dry_run)


def ventoy_json(theme: str | None = None, persistence_label: str = "PERSIST") -> dict:
    """Minimal Ventoy plugin config: theme + LUKS persistence marker for Kali."""
    cfg: dict = {
        "control": [{"VTOY_MENU_TIMEOUT": "0"}],
    }
    if theme:
        cfg["theme"] = {"file": f"/ventoy/theme/{theme}/theme.txt"}
    cfg["persistence"] = [
        {
            "image": "/ISOS/kali-linux-*.iso",
            "backend": f"/{persistence_label}/phntm-persist.img",
            "autosize": 0,
        }
    ]
    return cfg