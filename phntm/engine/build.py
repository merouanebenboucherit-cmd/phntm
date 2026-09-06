"""Build orchestration — the ordered step plan for turning a manifest into a stick."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from .. import VERSION
from ..catalog import catalog_version
from ..models import BuildManifest, CatalogEntry, StickMetadata
from ..sizer import compute_budget
from .copy import BuildReport, mount_root_for, run_copy_layer


class BuildError(RuntimeError):
    pass


@dataclass
class BuildStep:
    id: str
    title: str
    requires_hardware: bool
    optional: bool = False
    command: Callable[[], None] | None = None

    def __str__(self) -> str:
        tag = "hardware" if self.requires_hardware else "local"
        mark = "  ⇢ " if self.optional else "  → "
        return f"{mark}[{tag}] {self.title}"


def compose_steps(manifest: BuildManifest, catalog: Dict[str, CatalogEntry]) -> List[BuildStep]:
    """Build the ordered plan. Commands are attached only for the real run
    (dry-run shows the plan without touching anything)."""
    budget = compute_budget(manifest, catalog)
    if not budget.fits:
        raise BuildError(
            f"manifest '{manifest.name}' does not fit on a {manifest.tier}GB stick "
            f"({budget.used_gb:.1f}GB used of {budget.capacity_gb:.1f}GB usable). "
            "Pick a larger tier, drop components, or shrink vault/drop."
        )

    steps: List[BuildStep] = [
        BuildStep("concede", "Confirm stick identity & data-loss warning", requires_hardware=True),
        BuildStep("ventoy", "Install Ventoy (native or Docker — no sudo needed)", requires_hardware=True),
        BuildStep("mount", "Mount the exFAT data partition (Ventoy layout)", requires_hardware=True),
        BuildStep(
            "isos",
            "Stage ISOs → ISOS/ (sha256 verified, Ventoy-compatible)",
            requires_hardware=True,
        ),
        BuildStep(
            "tools",
            "Copy portable tools layer → TOOLS/",
            requires_hardware=True,
        ),
        BuildStep(
            "setup",
            "Write SETUP/ helper scripts + per-stick documentation",
            requires_hardware=True,
        ),
    ]

    if manifest.persistence.enabled:
        steps.append(
            BuildStep(
                "persist",
                f"Create LUKS persistence volume ({manifest.persistence.size_gb:.0f}GB) "
                "→ PERSIST/ (per-OS injection)",
                requires_hardware=True,
            )
        )
    if manifest.vault_gb > 0:
        steps.append(
            BuildStep(
                "vault",
                f"Create encrypted VAULT container ({manifest.vault_gb:.0f}GB, cryptsetup/LUKS)",
                requires_hardware=True,
            )
        )
    if manifest.drop_gb > 0:
        steps.append(
            BuildStep(
                "drop",
                f"Create DROP scratch folder ({manifest.drop_gb:.0f}GB plaintext spare)",
                requires_hardware=True,
            )
        )

    steps += [
        BuildStep(
            "theme",
            "Write ventoy.json theme + persistence plugin config",
            requires_hardware=True,
        ),
        BuildStep("metadata", "Write phntm.json stick metadata", requires_hardware=True),
        BuildStep("test", "QEMU boot-test the physical stick", requires_hardware=True, optional=True),
    ]
    return steps


def dry_run(manifest: BuildManifest, catalog: Dict[str, CatalogEntry]) -> str:
    from ..sizer import format_budget

    steps = compose_steps(manifest, catalog)
    budget = compute_budget(manifest, catalog)
    out = [f"PHNTM build plan — '{manifest.name}'"]
    out.append(f"  persona={manifest.persona.value}  tier={manifest.tier}GB  theme={manifest.theme or 'default'}")
    out.append("")
    out.append("BUDGET")
    out.append(format_budget(budget))
    out.append("STEPS")
    out.extend(f"  {s}" for s in steps)
    out.append("")
    out.append("Nothing was modified — dry run only. Add --device /dev/sdX to build for real.")
    return "\n".join(out)


def _device_ok(device: str, sysfs_root: str = "/sys") -> None:
    if not os.path.exists(device):
        raise BuildError(f"device '{device}' does not exist — plug in the USB stick first")
    # Removable check: sysfs is authoritative on Linux.
    sysfs = os.path.join(sysfs_root, "block", os.path.basename(device), "removable")
    if os.path.exists(sysfs):
        try:
            if int(open(sysfs).read().strip()) == 0:
                raise BuildError(
                    f"refusing to flash '{device}': not a removable device. Double-check you picked the stick."
                )
        except ValueError:
            pass


def _ventoy_driver(device: str):
    """Lazy import keeps build.py ↔ ventoy.py free of circular imports."""
    from .ventoy import install_ventoy

    return lambda: install_ventoy(device)


def run_build(
    manifest: BuildManifest,
    catalog: Dict[str, CatalogEntry],
    device: str,
    *,
    yes: bool = False,
    sysfs_root: str = "/sys",
    cache: str | os.PathLike | None = None,
    mount_hint: str | os.PathLike | None = None,
) -> Tuple[StickMetadata, "BuildReport"]:
    """Execute the real build. Every destructive action is gated on --yes.

    ``mount_hint``: fallback directory to stage into when the flashed stick's
    data partition never auto-mounts (user already has it mounted manually).

    Returns ``(stick_metadata, copy_report)`` — the copy report is the honest
    tally of what actually landed on the stick (see phntm/engine/copy.py).
    """
    from .metadata import write_metadata

    _device_ok(device, sysfs_root)
    if not yes:
        raise BuildError(
            f"destructive build on '{device}' requires --yes (the whole stick gets reformatted). "
            "Run with --dry-run first to review the plan."
        )

    def copy(parts):
        run_copy_layer(
            manifest, catalog, mount_root, parts=parts, report=report, verify=True, cache=cache
        )

    steps = compose_steps(manifest, catalog)
    report = BuildReport()
    mount_root: str | None = None
    meta = metadata_for(manifest, catalog, tool_version=VERSION)

    for step in steps:
        if step.optional:
            continue
        if step.id == "concede":
            print(f"  ✓ stick {device} confirmed — every byte on it will be wiped")
        elif step.id == "ventoy":
            _ventoy_driver(device)()
        elif step.id == "mount":
            mount_root = mount_root_for(device)
            if not mount_root and mount_hint is not None:
                hinted = Path(mount_hint)
                if hinted.is_dir():
                    mount_root = hinted
            if not mount_root:
                raise BuildError(
                    f"'{device}' finished flashing but its data partition never mounted. "
                    "Plug it into a desktop, copy data off, and try again — or pass --mount <dir>."
                )
            report.mount_root = mount_root
            print(f"  ✓ data partition mounted at {mount_root}")
        elif step.id == "isos":
            copy(["isos"])
        elif step.id == "tools":
            copy(["tools"])
        elif step.id == "setup":
            copy(["setup"])
        elif step.id == "persist":
            copy(["persist"])
        elif step.id == "vault":
            copy(["vault"])
        elif step.id == "drop":
            copy(["drop"])
        elif step.id == "theme":
            copy(["theme"])
        elif step.id == "metadata":
            path = write_metadata(mount_root, meta)
            print(f"  ✓ phntm.json written to {path}")
        else:
            raise BuildError(f"step '{step.id}' has no driver attached yet")

    return meta, report


def metadata_for(
    manifest: BuildManifest,
    catalog: Dict[str, CatalogEntry],
    tool_version: str = VERSION,
    catalog_ver: str | None = None,
) -> StickMetadata:
    return StickMetadata(
        tool_version=tool_version,
        catalog_version=catalog_ver or catalog_version(),
        created_at=manifest.created_at,
        name=manifest.name,
        persona=manifest.persona.value,
        tier=manifest.tier,
        persistence_gb=manifest.persistence.size_gb or 0.0,
        vault_gb=manifest.vault_gb,
        drop_gb=manifest.drop_gb,
        components=[
            {
                "id": c.id,
                "name": c.name,
                "size_gb": c.size_gb,
                "sha256": c.sha256,
                "release": c.release,
            }
            for c in (catalog[cid] for cid in manifest.components)
        ],
    )


def tool_is_on_path(tool: str) -> bool:
    return shutil.which(tool) is not None