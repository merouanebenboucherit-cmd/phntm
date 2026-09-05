"""Budget engine — does every plan fit on the stick? Refuses unrealistic builds."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .models import BuildManifest, CatalogEntry

# Ventoy + filesystem overhead eats a share of the nominal size.
# ~ usable = nominal - reservation, where reservation grows slowly with size.
def usable_capacity(tier_gb: int) -> float:
    return tier_gb - 1.5 - (tier_gb * 0.02)


@dataclass
class BudgetLine:
    label: str
    size_gb: float

    @property
    def human(self) -> str:
        if self.size_gb < 0.1:
            return f"{self.size_gb * 1000:.0f} MB"
        return f"{self.size_gb:.2f} GB"


@dataclass
class Budget:
    tier_gb: int
    capacity_gb: float
    lines: List[BudgetLine] = field(default_factory=list)

    @property
    def used_gb(self) -> float:
        return sum(l.size_gb for l in self.lines)

    @property
    def free_gb(self) -> float:
        return self.capacity_gb - self.used_gb

    @property
    def fits(self) -> bool:
        return self.free_gb >= 0

    @property
    def utilization(self) -> float:
        return self.used_gb / self.capacity_gb if self.capacity_gb else 0.0


def compute_budget(
    manifest: BuildManifest,
    catalog: Dict[str, CatalogEntry],
    include_persist: bool = True,
) -> Budget:
    capacity = usable_capacity(manifest.tier)
    budget = Budget(tier_gb=manifest.tier, capacity_gb=capacity)

    for cid in manifest.components:
        entry = catalog[cid]
        budget.lines.append(BudgetLine(label=f"📀 {entry.name}", size_gb=entry.size_gb))

    if include_persist and manifest.persistence.enabled:
        budget.lines.append(
            BudgetLine(label=f"🔐 LUKS persistence ({manifest.persistence.method})", size_gb=manifest.persistence.size_gb or 0.0)
        )
    if manifest.vault_gb > 0:
        budget.lines.append(BudgetLine(label=f"🛡️ VeraCrypt-style VAULT ({manifest.vault_gb:.0f}GB)", size_gb=manifest.vault_gb))
    if manifest.drop_gb > 0:
        budget.lines.append(BudgetLine(label=f"📍 DROP scratch space ({manifest.drop_gb:.0f}GB)", size_gb=manifest.drop_gb))

    # Filesystem + safety margin.
    budget.lines.append(BudgetLine(label="🧾 Filesystem/reserve", size_gb=manifest.tier - capacity))
    return budget


def format_budget(budget: Budget) -> str:
    lines = [
        f"  {line.human:<10} {line.label}" for line in budget.lines
    ]
    header = f"  {'USED':<10} {budget.used_gb:.2f} GB / {budget.capacity_gb:.2f} GB usable ({budget.utilization:.0%})"
    footer = f"  {'FREE':<10} {budget.free_gb:.2f} GB"
    if budget.fits:
        state = "✅ Fits"
        if budget.utilization >= 0.95:
            state += "  (⚠️ tight — within 5% of the limit)"
    else:
        state = "❌ OVER BUDGET"
    return "\n".join([header, *lines, footer, "", f"  → {state}"])


def overshoot(budget: Budget) -> float:
    """How far over budget a plan is (0 when it fits). Used by the CLI to advise."""
    return max(0.0, -budget.free_gb)