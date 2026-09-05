"""Ventoy install driver — native tool when present, Docker fallback otherwise.

PHNTM works without sudo: Ventoy itself is unprivileged (it submits the disk
ioctl via its own helpers), and the Docker fallback runs the official Ventoy
image with --privileged for those without the binary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .build import BuildError, tool_is_on_path

# Community-maintained images; overridable via env for air-gapped/verified use.
VENTOY_DOCKER_IMAGE = os.environ.get("PHNTM_VENTOY_IMAGE", "ventoy/ventoy:latest")


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
    def message(self) -> str:
        if self.mode == "native":
            return "ventoy detected on PATH"
        if self.mode == "docker":
            return f"no native ventoy; using docker image {VENTOY_DOCKER_IMAGE}"
        return "NEITHER ventoy NOR docker — install packages ventoy or docker first"


def install_ventoy(device: str, *, force: bool = False) -> None:
    """Flash Ventoy onto the device. Destructive — caller gates with --yes."""
    tool = VentoyTool.detect()
    if tool.mode == "none":
        raise BuildError(f"Cannot install Ventoy: {tool.message}. Aborting before touching {device}.")

    if tool.mode == "native":
        binary = shutil.which("Ventoy2Disk.sh") or shutil.which("ventoy")
        cmd = [
            binary or "Ventoy2Disk.sh",
            "-i" if not force else "-I",
            device,
        ]
        print(f"  ventoy (native): {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
    else:
        # Docker fallback — no-sudo path for this workstation.
        cmd = [
            "docker", "run", "--rm",
            "--privileged",
            "-v", "/dev:/dev:rw",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            VENTOY_DOCKER_IMAGE,
            ("-I" if force else "-i"),
            device,
        ]
        print(f"  ventoy (docker): docker run … {VENTOY_DOCKER_IMAGE} …")
        subprocess.run(cmd, check=True)


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