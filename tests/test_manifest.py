"""Manifest model tests — strictness protects every build."""

import pytest
from pydantic import ValidationError

from phntm.models import BuildManifest, Persona, Persistence


def test_valid_manifest():
    m = BuildManifest(persona=Persona.PENTEST, tier=32, components=["kali-linux", "seclists"])
    assert m.manifestVersion == 1
    assert m.persona == Persona.PENTEST
    assert m.persistence.enabled is False


def test_unknown_persona_rejected():
    with pytest.raises(ValidationError):
        BuildManifest(persona="not-a-persona", tier=32, components=["kali-linux"])


def test_tier_too_small_rejected():
    with pytest.raises(ValidationError):
        BuildManifest(persona=Persona.IT, tier=4, components=["hirens-boot-pe"])


def test_duplicate_components_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        BuildManifest(persona=Persona.IT, tier=32, components=["seclists", "seclists"])


def test_vault_must_be_smaller_than_tier():
    with pytest.raises(ValidationError, match="vault"):
        BuildManifest(persona=Persona.IT, tier=32, components=["seclists"], vault_gb=64)


def test_persistence_requires_size():
    with pytest.raises(ValidationError):
        BuildManifest(
            persona=Persona.PENTEST,
            tier=32,
            components=["kali-linux"],
            persistence=Persistence(enabled=True),
        )


def test_bad_component_id_rejected():
    with pytest.raises(ValidationError, match="id"):
        BuildManifest(persona=Persona.IT, tier=32, components=["UPPER_CASE_BAD"])


def test_manifest_dumps_and_reloads_roundtrip():
    m = BuildManifest(persona=Persona.IT, tier=16, components=["memtest86plus"])
    m2 = BuildManifest.model_validate_json(m.model_dump_json())
    assert m2 == m