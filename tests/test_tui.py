"""Wizard (TUI) flow tests — driven headless with Textual's test pilot.

Runs inside ``asyncio.run`` so no pytest-asyncio plugin is required.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from textual.widgets import Input, ProgressBar, RadioButton, RadioSet

from phntm.models import BuildManifest, Persona
from phntm.sizer import compute_budget
from phntm.tui import PersonaScreen, PhntmWizard, PlanScreen, TierScreen


def _run(coro):
    return asyncio.run(coro)


async def _goto_plan(app, pilot, tier_index=1):
    """Drive the wizard headless: persona(0) → tier(tier_index) → plan."""
    await pilot.pause()  # let PersonaScreen mount
    assert isinstance(app.screen, PersonaScreen)
    await pilot.click(app.screen.query_one(RadioSet).query(RadioButton)[0])
    await pilot.click("#next")
    await pilot.pause()
    assert isinstance(app.screen, TierScreen)
    tier_radio = app.screen.query_one(RadioSet).query(RadioButton)[tier_index]
    await pilot.click(tier_radio)
    await pilot.click("#next")
    await pilot.pause()
    assert isinstance(app.screen, PlanScreen)


def test_wizard_opens_on_persona_screen():
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, PersonaScreen)
            radioset = app.screen.query_one(RadioSet)
            assert radioset.pressed_index == 0  # first persona preselected
            assert len(radioset.query(RadioButton)) >= 5  # 4 personas + general

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
            assert "GB" in label  # tier estimate labels carry a GB size

            await pilot.click("#back")
            await pilot.pause()
            assert isinstance(app.screen, PersonaScreen)

    _run(flow())


def test_wizard_tier_to_plan_with_live_meter():
    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await _goto_plan(app, pilot, tier_index=1)
            plan = app.screen
            expected = compute_budget(plan.manifest, app.catalog)
            meter = app.screen.query_one("#meter", ProgressBar)
            assert meter.progress == pytest.approx(expected.used_gb)
            assert meter.total == pytest.approx(
                max(expected.capacity_gb, expected.used_gb)
            )
            assert plan.manifest.persona in Persona
            assert plan.manifest.tier > 0
            assert plan.manifest.components

    _run(flow())


def test_wizard_saves_valid_manifest(tmp_path):
    out = tmp_path / "build.json"

    async def flow():
        app = PhntmWizard()
        async with app.run_test() as pilot:
            await _goto_plan(app, pilot, tier_index=1)
            input_widget = app.screen.query_one("#out", Input)
            input_widget.value = str(out)
            # the save row is below the fold on a terminal-sized screen
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