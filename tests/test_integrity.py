"""Data integrity — every preset must pin real catalog entries that fit its tier."""

from phntm.catalog import load_catalog
from phntm.presets import available_personas, manifest_from_preset, tiers_for
from phntm.sizer import compute_budget


def test_all_presets_are_valid_and_self_consistent():
    catalog = load_catalog()
    personas = available_personas()
    assert len(personas) == 5
    checked = 0
    for persona in personas:
        for tier in tiers_for(persona):
            manifest = manifest_from_preset(persona, tier)
            # The manifest itself must validate on roundtrip.
            assert manifest.persona == persona
            assert manifest.tier == tier
            assert manifest.manifestVersion == 1
            # Every pinned id must resolve in the catalog.
            missing = [cid for cid in manifest.components if cid not in catalog]
            assert not missing, f"{persona.value}/{tier}: unknown ids {missing}"
            # Pinned components have nothing broken at the catalog level:
            # every persona tag must be a known persona (data sanity), and
            # presets may span families (e.g. tor-browser in an IT build).
            for cid in manifest.components:
                entry = catalog[cid]
                assert all(t in {p.value for p in __import__("phntm.models", fromlist=["Persona"]).Persona} for t in {t_.value for t_ in entry.persona_tags}), (
                    f"{persona.value}/{tier}: {cid} has unknown persona tags"
                )
            # And it must fit the tier budget (with overhead).
            budget = compute_budget(manifest, catalog)
            assert budget.free_gb >= 0, (
                f"{persona.value}/{tier}: over budget by {-budget.free_gb:.1f} GB "
                f"(used {budget.used_gb:.1f} of {budget.capacity_gb:.1f})"
            )
            checked += 1
    assert checked == 14, f"expected the full preset matrix (14), saw {checked}"


def test_all_five_personas_are_covered_by_presets():
    from phntm.models import Persona

    covered = {p for p in available_personas()}
    assert covered == set(Persona)