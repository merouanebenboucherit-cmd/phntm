"""Budget engine tests — plan must fit or the tool must say so loudly."""

from phntm.catalog import load_catalog
from phntm.models import Persona
from phntm.presets import manifest_from_preset
from phntm.sizer import compute_budget, overshoot, usable_capacity


def test_usable_capacity_less_than_nominal():
    assert usable_capacity(32) < 32
    assert usable_capacity(16) > 10


def test_every_ship_preset_fits_its_tier():
    catalog = load_catalog()
    for persona in [Persona.IT, Persona.PENTEST, Persona.DFIR, Persona.PRIVACY, Persona.GENERAL]:
        from phntm.presets import tiers_for

        for tier in tiers_for(persona):
            manifest = manifest_from_preset(persona, tier)
            budget = compute_budget(manifest, catalog)
            assert budget.fits, (
                f"{persona.value}/{tier}GB over by {overshoot(budget):.2f}GB — "
                "preset needs trimming or a capacity bump"
            )


def test_overshoot_detects_overflow():
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.GENERAL, 64)
    # Simulate the full-stack 128GB build squeezed into 64GB by force.
    manifest2 = manifest.model_copy(update={"tier": 16})
    budget = compute_budget(manifest2, catalog)
    assert not budget.fits
    assert overshoot(budget) > 0


def test_budget_components_count_matches_manifest():
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.DFIR, 32)
    budget = compute_budget(manifest, catalog)
    comp_lines = [l for l in budget.lines if l.label.startswith("📀")]
    assert len(comp_lines) == len(manifest.components)