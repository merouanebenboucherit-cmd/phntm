"""phntm.json — the stick's identity. Written at build, read by status/update."""

from __future__ import annotations

import json
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