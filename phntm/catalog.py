"""Component catalog loading and verification."""

from __future__ import annotations

import json
from importlib import resources
from typing import Dict

from .models import CatalogEntry

_CATALOG_FILE = "catalog.json"


def load_catalog(raw: dict | None = None) -> Dict[str, CatalogEntry]:
    """Load and validate the component catalog from bundled JSON data."""
    if raw is None:
        raw = json.loads(resources.files("phntm.data").joinpath(_CATALOG_FILE).read_text())
    version = raw.get("catalogVersion", "catalog-unknown")
    entries: Dict[str, CatalogEntry] = {}
    for item in raw["entries"]:
        entry = CatalogEntry.model_validate(item)
        if entry.id in entries:
            raise ValueError(f"duplicate catalog id: {entry.id}")
        entries[entry.id] = entry
    if not entries:
        raise ValueError("catalog is empty")
    return entries


def catalog_version(raw: dict | None = None) -> str:
    if raw is None:
        raw = json.loads(resources.files("phntm.data").joinpath(_CATALOG_FILE).read_text())
    return raw.get("catalogVersion", "catalog-unknown")


def resolve_components(ids: list[str], catalog: Dict[str, CatalogEntry]) -> list[CatalogEntry]:
    """Resolve manifest component ids against the catalog, failing fast on unknowns."""
    missing = [cid for cid in ids if cid not in catalog]
    if missing:
        raise KeyError(
            f"unknown component(s) in manifest: {', '.join(sorted(missing))}. "
            "Check phntm update --catalog or fix the manifest."
        )
    return [catalog[cid] for cid in ids]