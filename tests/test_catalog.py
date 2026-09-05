"""Catalog integrity — every id unique, entries sane, presets resolve."""

import pytest

from phntm.catalog import load_catalog, resolve_components
from phntm.models import Persona, Tier
from phntm.presets import (
    manifest_from_preset,
    resolve_preset,
    tiers_for,
    available_personas,
)


def test_catalog_loads_and_is_nonempty():
    catalog = load_catalog()
    assert len(catalog) >= 20
    assert "kali-linux" in catalog


def test_catalog_ids_unique_and_sluglike():
    catalog = load_catalog()
    ids = list(catalog)
    assert len(ids) == len(set(ids))
    for cid in ids:
        assert cid == cid.lower()
        assert "-" in cid or cid.isalnum()
        assert not cid.startswith("-")


def test_catalog_urls_are_http():
    for entry in load_catalog().values():
        assert entry.url.startswith("http")


def test_every_persona_has_ship_tiers():
    assert {p.value for p in available_personas()} == {"it", "pentest", "dfir", "privacy", "general"}
    for p in available_personas():
        assert tiers_for(p), f"{p.value} has no tiers"


def test_preset_components_all_exist_in_catalog():
    catalog = load_catalog()
    for persona in available_personas():
        for tier in tiers_for(persona):
            preset = resolve_preset(persona, tier)
            missing = [c for c in preset.components if c not in catalog]
            assert not missing, f"{persona.value}/{tier}GB references unknown ids: {missing}"


def test_preset_manifest_valid_and_sized():
    catalog = load_catalog()
    for persona in [Persona.IT, Persona.PENTEST, Persona.DFIR, Persona.PRIVACY, Persona.GENERAL]:
        for tier in tiers_for(persona):
            manifest = manifest_from_preset(persona, tier)
            resolve_components(manifest.components, catalog)  # must not raise
            assert manifest.tier == tier
            if manifest.persistence.enabled:
                assert manifest.persistence.size_gb == resolve_preset(persona, tier).persist_gb