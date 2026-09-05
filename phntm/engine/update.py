"""Catalog-vs-stick freshness diff.

`phntm check` compares what a manifest or stick pins against the current
catalog. A later release grows this module into a full `phntm upgrade` (download + apply);
today it reports truth locally and honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from ..models import CatalogEntry, ComponentPin


@dataclass
class Diff:
    current: List[str] = field(default_factory=list)
    stale: List[Tuple[str, str | None, str | None]] = field(default_factory=list)
    vanished: List[str] = field(default_factory=list)

    @property
    def outdated(self) -> bool:
        return bool(self.stale or self.vanished)


def diff_pins(
    pins: List[ComponentPin],
    catalog: Dict[str, CatalogEntry],
) -> Diff:
    diff = Diff()
    for pin in pins:
        entry = catalog.get(pin.id)
        if entry is None:
            diff.vanished.append(pin.id)
        elif pin.release and entry.release and pin.release != entry.release:
            diff.stale.append((pin.id, pin.release, entry.release))
        else:
            diff.current.append(pin.id)
    return diff