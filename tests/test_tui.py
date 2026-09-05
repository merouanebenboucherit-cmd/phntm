"""Wizard (TUI) flow tests — driven headless with Textual's test pilot.

Runs inside ``asyncio.run`` so no pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from textual.widgets import Button, Checkbox, Input, ProgressBar, RadioButton, RadioSet

from phntm.catalog import load_catalog
from phntm.models import BuildManifest, Persona
from phntm.sizer import compute_budget
from phntm.tui import ComponentsScreen, PersonaScreen, PhntmWizard, PlanScreen, TierScreen


def _run(coro):
    return asyncio.run(coro)


async def _goto_plan(app, pilot, tier_index=1, persona_index=0):
    """Drive: persona(persona_index) → tier(tier_index) → components → plan."""
    await pilot.pause()
    assert isinstance(app.screen, PersonaScreen)
    await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[persona_index])
    await pilot.click("#next")
    await pilot.pause()
    assert isinstance(app.screen, TierScreen)
    await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[tier_index])
    await pilot.click("#next")
    await pilot.pause()
    assert isinstance(app.screen, ComponentsScreen)
    # default: all preset components checked → fits → next is enabled
    assert not app.screen.query_one("#next", Button).disabled
    await pilot.click("#next")
    await pilot.pause()
    assert isinstance(app.screen, PlanScreen)


# ---- persona + tier flow --------------------------------------------------

def test_wizard_opens_on_persona_screen():
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, PersonaScreen)
            radioset = app.screen.query_one(RadioSet)
            assert radioset.pressed_index == 0
            assert len(radioset.query(RadioButton)) >= 5

    _run(flow())


def test_wizard_persona_to_tier_navigation():
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            first = app.screen.query_one(RadioSet).query(RadioButton)[0]
            await pilot.click(first)
            await pilot.click("#next")
            await pilot.pause()
            assert isinstance(app.screen, TierScreen)
            tiers = app.screen.query_one(RadioSet)
            assert tiers.pressed_index >= 0
            label = str(tiers.pressed_button.label)
            assert "GB" in label
            await pilot.click("#back")
            await pilot.pause()
            assert isinstance(app.screen, PersonaScreen)

    _run(flow())


# ---- components screen -----------------------------------------------------

def test_components_screen_shows_preset_components():
    """The components screen lists the preset's ISOs and tools with live meter."""
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            # pentest persona (index 1), 64 GB tier (index 2 typically)
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[1])
            await pilot.click("#next")
            await pilot.pause()
            assert isinstance(app.screen, TierScreen)
            # pentest tier indices: 16/32/64/128 → index 2 = 64 GB
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[2])
            await pilot.click("#next")
            await pilot.pause()
            assert isinstance(app.screen, ComponentsScreen)
            cs = app.screen
            catalog = app.catalog
            manifest = cs.manifest  # base preset
            checkboxes = list(cs.walk_children(Checkbox))
            # one per component + LUKS persistence
            assert len(checkboxes) >= len(manifest.components)
            # all preset components checked by default
            for cid in manifest.components:
                assert cs.query_one(f"#cb-{cid}", Checkbox).value is True
            # meter shows non-zero used
            assert cs.query_one("#meter", ProgressBar).progress > 0

    _run(flow())


def test_toggling_component_updates_meter():
    """Unchecking a component shrinks the meter; disabling all Next blocks saving."""
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[0])  # IT
            await pilot.click("#next")
            await pilot.pause()
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[0])  # first tier
            await pilot.click("#next")
            await pilot.pause()
            assert isinstance(app.screen, ComponentsScreen)
            cs = app.screen
            first_id = cs.manifest.components[0]
            checkbox = cs.query_one(f"#cb-{first_id}", Checkbox)
            meter = cs.query_one("#meter", ProgressBar)
            progress_before = meter.progress
            entry = app.catalog[first_id]

            # uncheck first component → meter must shrink
            checkbox.value = False
            await pilot.pause()
            assert meter.progress == pytest.approx(progress_before - entry.size_gb)
            # next still enabled (IT presets fit)
            assert not cs.query_one("#next", Button).disabled

            # uncheck everything → next must become disabled
            for cid in cs.manifest.components:
                cs.query_one(f"#cb-{cid}", Checkbox).value = False
            await pilot.pause()
            assert cs.query_one("#next", Button).disabled

    _run(flow())


def test_persistence_checkbox_pentest():
    """Pentest presets ship a persistence checkbox; unchecking it shrinks the meter."""
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[1])  # pentest
            await pilot.click("#next")
            await pilot.pause()
            await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[2])  # 64 GB
            await pilot.click("#next")
            await pilot.pause()
            cs = app.screen
            assert isinstance(cs, ComponentsScreen)
            persist_cb = cs.query_one("#cb-persist", Checkbox)
            meter = cs.query_one("#meter", ProgressBar)
            progress_with = meter.progress

            persist_cb.value = False
            await pilot.pause()
            assert meter.progress < progress_with
            # persistence size is 10 GB for pentest 64 GB
            assert persist_cb.label.plain.startswith("🔐 LUKS")

    _run(flow())


# ---- plan screen + save ---------------------------------------------------

def test_wizard_tier_to_plan_with_live_meter():
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await _goto_plan(app, pilot, tier_index=1)
            assert isinstance(app.screen, PlanScreen)
            expected = compute_budget(app.screen.manifest, app.catalog)
            meter = app.screen.query_one("#meter", ProgressBar)
            assert meter.progress == pytest.approx(expected.used_gb)
            assert meter.total == pytest.approx(
                max(expected.capacity_gb, expected.used_gb)
            )
            assert app.screen.manifest.persona in Persona
            assert app.screen.manifest.tier > 0
            assert app.screen.manifest.components

    _run(flow())


def test_wizard_saves_valid_manifest(tmp_path):
    out = tmp_path / "build.json"

    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await _goto_plan(app, pilot, tier_index=1)
            input_widget = app.screen.query_one("#out", Input)
            input_widget.value = str(out)
            from textual.containers import VerticalScroll
            app.screen.query_one(VerticalScroll).scroll_end(animate=False)
            await pilot.pause()
            await pilot.click("#save")
            await pilot.pause()

        assert out.exists()

    _run(flow())

    data = json.loads(out.read_text())
    manifest = BuildManifest.model_validate(data)
    assert manifest.persona in Persona
    assert manifest.tier in (16, 32, 64, 128)
    assert manifest.components, "preset must resolve to components"