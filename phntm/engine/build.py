"""Build orchestration — the ordered step plan for turning a manifest into a stick."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List

from ..models import BuildManifest, CatalogEntry, StickMetadata
from ..sizer import compute_budget


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
        BuildStep("partition", "Create exFAT data partition layout", requires_hardware=True),
        BuildStep(
            "isos",
            "Stage ISOs → ISOS/ (sha256 verified, Ventoy-compatible)",
            requires_hardware=True,
        ),
        BuildStep(
            "tools",
            "Copy portable tools layer → TOOLS/ (incl. PHNTM scripts)",
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
                f"Create encrypted VAULT volume ({manifest.vault_gb:.0f}GB, cryptsetup/LUKS)",
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
        BuildStep("theme", "Write ventoy.json theme + boot-menu customization", requires_hardware=False),
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


def _device_ok(device: str) -> None:
    if not os.path.exists(device):
        raise BuildError(f"device '{device}' does not exist — plug in the USB stick first")
    # Removable check: sysfs is authoritative on Linux.
    sysfs = f"/sys/block/{os.path.basename(device)}/removable"
    if os.path.exists(sysfs):
        try:
            if int(open(sysfs).read().strip()) == 0:
                raise BuildError(
                    f"refusing to flash '{device}': not a removable device. Double-check you picked the stick."
                )
        except ValueError:
            pass


def run_build(
    manifest: BuildManifest,
    catalog: Dict[str, CatalogEntry],
    device: str,
    *,
    yes: bool = False,
) -> StickMetadata:
    """Execute the real build. Every destructive action is gated on --yes."""
    _device_ok(device)
    if not yes:
        raise BuildError(
            f"destructive build on '{device}' requires --yes (the whole stick gets reformatted). "
            "Run with --dry-run first to review the plan."
        )

    steps = compose_steps(manifest, catalog)
    for step in steps:
        if step.optional:
            continue
        if step.command is None:
            raise BuildError(
                f"step '{step.id}' has no driver attached yet."
            )
        step.command()

    return metadata_for(manifest, catalog, tool_version="1.0.0")


def metadata_for(
    manifest: BuildManifest,
    catalog: Dict[str, CatalogEntry],
    tool_version: str,
    catalog_version: str = "catalog-2026.09",
) -> StickMetadata:
    return StickMetadata(
        tool_version=tool_version,
        catalog_version=catalog_version,
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


def require_root() -> None:
    if os.geteuid() != 0:
        # Most operations are delegated to Ventoy/native tools or Docker,
        # but cryptsetup mount work may need privileges — surface it early.
        pass