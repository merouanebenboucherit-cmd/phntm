"""Preset resolution — persona x tier definitions ship with the tool."""

from __future__ import annotations

import json
from importlib import resources
from typing import Dict, List, Tuple

from pydantic import BaseModel, Field

from .models import BuildManifest, Persona

_PRESETS_FILE = "presets.json"


class TierPreset(BaseModel):
    name: str
    components: List[str]  # validated against catalog at build time
    vault_gb: float
    drop_gb: float
    persist_gb: float


class PersonaPreset(BaseModel):
    label: str
    emoji: str
    recommended_tier: int = Field(ge=16, le=128)
    description: str
    tiers: Dict[int, TierPreset]  # tier GB -> preset


def load_presets() -> Dict[str, PersonaPreset]:
    raw = json.loads(resources.files("phntm.data").joinpath(_PRESETS_FILE).read_text())
    personas: Dict[str, PersonaPreset] = {}
    for name, p in raw["personas"].items():
        personas[name] = PersonaPreset.model_validate(p)
    return personas


def available_personas() -> list[Persona]:
    return [p for p in Persona if p != Persona.GENERAL] + [Persona.GENERAL]


def tiers_for(persona: Persona) -> list[int]:
    presets = load_presets()
    return sorted(presets[persona.value].tiers.keys())


def resolve_preset(persona: Persona, tier: int) -> TierPreset:
    presets = load_presets()
    persona_data = presets[persona.value]
    if tier not in persona_data.tiers:
        raise KeyError(
            f"persona '{persona.value}' has no preset for {tier}GB "
            f"(available: {sorted(persona_data.tiers)})."
        )
    return persona_data.tiers[tier]


def manifest_from_preset(
    persona: Persona,
    tier: int,
    *,
    name: str | None = None,
    theme: str | None = None,
) -> BuildManifest:
    """Generate a valid BuildManifest from a named preset."""
    preset = resolve_preset(persona, tier)
    return BuildManifest(
        name=name or preset.name,
        persona=persona,
        tier=tier,
        components=preset.components,
        vault_gb=preset.vault_gb,
        drop_gb=preset.drop_gb,
        persistence={"enabled": preset.persist_gb > 0, "size_gb": preset.persist_gb or 0.0},
        theme=theme,
    )