"""phntm.json — the stick's identity. Written at build, read by status/update."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..models import StickMetadata

METADATA_FILE = "phntm.json"


def write_metadata(root: str | Path, metadata: StickMetadata) -> Path:
    path = Path(root) / METADATA_FILE
    path.write_text(metadata.model_dump_json(indent=2) + "\n")
    return path


def read_metadata(root: str | Path) -> StickMetadata:
    path = Path(root) / METADATA_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"no {METADATA_FILE} at '{path}'. Is this a PHNTM-built stick?"
        )
    return StickMetadata.model_validate(json.loads(path.read_text()))


def mountpoints_for_device(device: str | Path) -> list[Path]:
    """Root-free mount lookup for a block device (its partitions included).

    Uses `lsblk -o MOUNTPOINTS`; returns absolute dirs only, empty on failure.
    """
    try:
        out = subprocess.check_output(
            ["lsblk", "-n", "-o", "MOUNTPOINTS", str(device)],
            stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    return [Path(line.strip()) for line in out.splitlines() if line.strip().startswith("/")]


def read_metadata_stick(target: str | Path) -> tuple[StickMetadata, Path]:
    """Stick-aware metadata read — accepts a mount dir OR a block device.

    Returns ``(metadata, phntm.json path)``. Raises :class:`FileNotFoundError`
    when no PHNTM metadata can be found anywhere on the target.
    """
    target = Path(target)
    if target.is_dir():
        return read_metadata(target), target / METADATA_FILE
    mounts = mountpoints_for_device(target)
    for mp in mounts:
        try:
            return read_metadata(mp), mp / METADATA_FILE
        except FileNotFoundError:
            continue
    detail = f" (mounted at: {', '.join(str(m) for m in mounts)})" if mounts else ""
    raise FileNotFoundError(
        f"no {METADATA_FILE} on '{target}'{detail}. Is this a PHNTM-built stick? "
        "Run a build with --mount, or point status at the mounted folder."
    )


def status_snippet(meta: StickMetadata) -> str:
    comps = "\n".join(f"    • {c.id}  ({c.size_gb:.2f} GB)" for c in meta.components)
    return "\n".join(
        [
            f"  name           {meta.name}",
            f"  persona        {meta.persona}",
            f"  tier           {meta.tier} GB",
            f"  built          {meta.created_at}",
            f"  tool           v{meta.tool_version} (catalog {meta.catalog_version})",
            f"  persistence    {meta.persistence_gb:.1f} GB",
            f"  vault          {meta.vault_gb:.1f} GB  |  drop {meta.drop_gb:.1f} GB",
            "  components:",
            comps,
        ]
    )