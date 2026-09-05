"""Update diff — the brain behind `phntm check`."""

from phntm.catalog import load_catalog
from phntm.engine.update import diff_pins
from phntm.models import ComponentPin, Persona
from phntm.presets import manifest_from_preset


def pins_for(persona, tier):
    from phntm.engine.build import metadata_for

    catalog = load_catalog()
    return metadata_for(manifest_from_preset(persona, tier), catalog, tool_version="1.0.0").components


def test_fresh_stick_is_fully_current():
    catalog = load_catalog()
    diff = diff_pins(pins_for(Persona.IT, 32), catalog)
    assert not diff.outdated
    assert len(diff.current) == 12
    assert not diff.stale and not diff.vanished


def test_old_release_detected_as_stale():
    catalog = load_catalog()
    pins = pins_for(Persona.PENTEST, 32)
    # Pretend the stick carries an ancient Kali.
    pin = next(p for p in pins if p.id == "kali-linux")
    pin.release = "2023.1"
    diff = diff_pins(pins, catalog)
    assert diff.outdated
    assert ("kali-linux", "2023.1", catalog["kali-linux"].release) in diff.stale


def test_component_that_left_catalog_is_vanished():
    catalog = load_catalog()
    pins = pins_for(Persona.DFIR, 16)
    pins.append(ComponentPin(id="retired-tool", name="old", size_gb=1.0))
    diff = diff_pins(pins, catalog)
    assert "retired-tool" in diff.vanished
    assert diff.outdated