"""PHNTM core data models.

Every stick is described by a BuildManifest (v1). The manifest drives the
sizer, the build orchestrator, and the metadata written to the device
(phntm.json). All models validate strictly — a bad manifest never builds.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Registry of personas PHNTM ships with.
class Persona(str, Enum):
    IT = "it"
    PENTEST = "pentest"
    DFIR = "dfir"
    PRIVACY = "privacy"
    GENERAL = "general"

    @property
    def label(self) -> str:
        return {
            "it": "IT Tech",
            "pentest": "Pentester",
            "dfir": "DFIR Analyst",
            "privacy": "Privacy User",
            "general": "General Mix",
        }[self.value]

    @property
    def emoji(self) -> str:
        return {
            "it": "🛠️",
            "pentest": "🎯",
            "dfir": "🔍",
            "privacy": "🕶️",
            "general": "🧰",
        }[self.value]


# Tiers ship as named presets; the manifest itself may use any capacity >= 8 GB.
class Tier(int, Enum):
    GB16 = 16
    GB32 = 32
    GB64 = 64
    GB128 = 128


class Persistence(BaseModel):
    """Per-OS persistence, e.g. a LUKS volume so Kali survives reboots."""

    enabled: bool = False
    size_gb: Optional[float] = Field(default=None, ge=0)
    method: Literal["luks"] = "luks"

    @model_validator(mode="after")
    def _require_size_when_enabled(self) -> "Persistence":
        if self.enabled and self.size_gb is None:
            raise ValueError("size_gb is required when persistence is enabled")
        if not self.enabled:
            self.size_gb = 0.0
        return self


class CatalogEntry(BaseModel):
    """One downloadable/installable component in the catalog."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    name: str
    kind: Literal["iso", "portable", "tool", "custom"]
    categories: List[str] = Field(min_length=1)
    persona_tags: List[Persona] = Field(default_factory=list)
    size_gb: float = Field(gt=0)
    url: str
    download_url: Optional[str] = None
    homepage: Optional[str] = None
    sha256: Optional[str] = None
    release: Optional[str] = None
    ventoy_compatible: bool = True
    redistributable: bool = True
    notes: Optional[str] = None

    @field_validator("url", "download_url")
    @classmethod
    def _url_must_be_http(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"url must be http(s): {v}")
        return v


class BuildManifest(BaseModel):
    """The declaration of intent: what goes on the stick and how."""

    manifestVersion: int = Field(default=1, ge=1)
    name: str = Field(default="PHNTM Build", min_length=1, max_length=64)
    persona: Persona
    tier: int = Field(ge=8, le=256)
    components: List[str] = Field(min_length=1)
    persistence: Persistence = Field(default_factory=Persistence)
    vault_gb: float = Field(default=2.0, ge=0, le=256)
    drop_gb: float = Field(default=1.0, ge=0, le=256)
    theme: Optional[str] = None
    created_at: str = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    @field_validator("components")
    @classmethod
    def _components_unique(cls, v: List[str]) -> List[str]:
        seen: set[str] = set()
        dupes = [c for c in v if c in seen or seen.add(c)]
        if dupes:
            raise ValueError(f"duplicate components: {dupes}")
        return v

    @field_validator("components")
    @classmethod
    def _components_sluglike(cls, v: List[str]) -> List[str]:
        bad = [c for c in v if not valid_component_id(c)]
        if bad:
            raise ValueError(
                f"components must be lowercase slugs (letters/digits/hyphens): {bad}"
            )
        return v

    @model_validator(mode="after")
    def _size_sanity(self) -> "BuildManifest":
        if self.vault_gb >= self.tier:
            raise ValueError("vault_size must be smaller than the stick capacity")
        return self


class ComponentPin(BaseModel):
    """Resolved component pinned into a build (id + catalog snapshot)."""

    id: str
    name: str
    size_gb: float
    sha256: Optional[str] = None
    release: Optional[str] = None


class StickMetadata(BaseModel):
    """phntm.json — written to every built stick for status/update."""

    model_config = ConfigDict(populate_by_name=True)

    schema_name: Literal["phntm/metadata"] = Field(
        default="phntm/metadata",
        validation_alias="schema",
        serialization_alias="schema",
    )
    file_version: int = 1
    tool_version: str
    catalog_version: str = "catalog-1970.01"
    created_at: str
    name: str
    persona: str
    tier: int
    persistence_gb: float
    vault_gb: float
    drop_gb: float
    components: List[ComponentPin]


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]+$")


def valid_component_id(candidate: str) -> bool:
    return bool(_ID_RE.match(candidate))