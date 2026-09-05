"""M2 — the PHNTM wizard: a guided Textual TUI.

Walks persona → tier → plan with a *live size meter*, then saves the manifest.
Pure frontend: every decision routes through the same engine as the CLI,
so a manifest saved here is byte-identical to one made with
``phntm manifest new``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    ProgressBar,
    RadioButton,
    RadioSet,
    Static,
)

from . import VERSION
from .catalog import load_catalog, resolve_components
from .models import BuildManifest, Persona
from .presets import available_personas, load_presets, manifest_from_preset, tiers_for
from .sizer import Budget, compute_budget, format_budget

GHOST = "#38e08e"  # neon ghost green
BG = "#0d1117"
PANEL = "#0f141a"
BORDER = "#30363d"
MUTED = "#8b949e"

CSS = f"""
Screen {{
    background: {BG};
    color: #c9d1d9;
}}

#step {{
    padding: 1 3;
    height: 1fr;
}}

.step-tag {{
    color: {GHOST};
    text-style: bold;
}}

.title {{
    text-style: bold;
    margin-bottom: 1;
}}

RadioSet {{
    border: round {BORDER};
    background: {PANEL};
    padding: 0 1;
    height: auto;
}}

RadioSet:focus-within {{
    border: round {GHOST};
}}

RadioButton {{
    padding-left: 1;
}}

#desc {{
    margin: 1 0;
    color: {MUTED};
}}

Button {{
    margin-top: 1;
    margin-right: 1;
}}

Button.primary {{
    background: {GHOST};
    color: {BG};
    border: tall {GHOST};
}}

#meter {{
    height: 4;
    margin: 1 0 0 0;
}}

#meter .bar--bar {{
    background: {GHOST};
}}

#meter.over .bar--bar {{
    background: #ff5555;
}}

#used {{
    margin-bottom: 1;
    color: {MUTED};
}}

#budget {{
    background: {PANEL};
    padding: 1 2;
    border: round {BORDER};
    height: auto;
}}

#hint {{
    color: {MUTED};
    margin: 1 0;
}}

Input {{
    margin-top: 1;
}}

#saveline {{
    height: auto;
}}

Footer {{
    background: #161b22;
}}
"""


@dataclass
class WizardState:
    """Progress shared across wizard screens."""

    persona: Persona | None = None
    tier: int | None = None
    manifest: BuildManifest | None = field(default=None)


class PersonaScreen(Screen[None]):
    """Step 1 — who is this stick for?"""

    BINDINGS = [("escape", "app.pop_screen", "quit")]

    def compose(self) -> ComposeResult:
        app = cast(PhntmWizard, self.app)
        yield Footer()
        with Vertical(id="step"):
            yield Static("STEP 1/3 — who is this stick for?", classes="step-tag")
            yield Static("Choose a persona", classes="title")
            with RadioSet(id="personas"):
                default = app.state.persona or available_personas()[0]
                for persona in available_personas():
                    data = app.presets[persona.value]
                    yield RadioButton(
                        f"{data.emoji} {data.label} — {data.description}",
                        value=(persona == default),
                    )
            yield Static(
                "Personae ship curated sets of ISOs + tools per tier. "
                "You can tune the plan next.",
                id="desc",
            )
            yield Horizontal(Button("Next →", id="next", variant="primary"))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        label = str(event.pressed.label)
        self.query_one("#desc", Static).update(f"→ {label}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "next":
            return
        idx = self.query_one(RadioSet).pressed_index
        if idx < 0:
            self.app.notify("Pick a persona to continue", severity="warning")
            return
        app = cast(PhntmWizard, self.app)
        app.state.persona = available_personas()[idx]
        self.app.push_screen(TierScreen())


class TierScreen(Screen[None]):
    """Step 2 — how big is the stick? Live estimated sizes per tier."""

    BINDINGS = [("escape", "app.pop_screen", "back")]

    def compose(self) -> ComposeResult:
        app = cast(PhntmWizard, self.app)
        persona = app.state.persona
        assert persona is not None
        data = app.presets[persona.value]
        yield Footer()
        with Vertical(id="step"):
            yield Static(
                f"STEP 2/3 — {data.emoji} {data.label}", classes="step-tag"
            )
            yield Static("Choose the stick size", classes="title")
            with RadioSet(id="tiers"):
                for tier in tiers_for(persona):
                    preset = data.tiers[tier]
                    manifest = manifest_from_preset(persona, tier)
                    used = compute_budget(manifest, app.catalog).used_gb
                    yield RadioButton(
                        f"{tier} GB — {preset.name}  (≈{used:.1f} GB content)"
                        + ("  ✦ recommended" if tier == data.recommended_tier else ""),
                        value=(tier == (app.state.tier or data.recommended_tier)),
                    )
            yield Static(
                "The meter on the next screen refuses plans that physically "
                "won't fit on the stick.",
                id="desc",
            )
            yield Horizontal(Button("← Back", id="back"), Button("Preview plan →", id="next", variant="primary"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = cast(PhntmWizard, self.app)
        if event.button.id == "back":
            self.app.pop_screen()
            return
        if event.button.id != "next":
            return
        persona = app.state.persona
        assert persona is not None
        idx = self.query_one(RadioSet).pressed_index
        if idx < 0:
            self.app.notify("Pick a tier to continue", severity="warning")
            return
        app.state.tier = tiers_for(persona)[idx]
        manifest = manifest_from_preset(persona, app.state.tier)
        budget = compute_budget(manifest, app.catalog)
        self.app.push_screen(PlanScreen(manifest, budget))


class PlanScreen(Screen[None]):
    """Step 3 — the full plan with a live size meter, then save."""

    BINDINGS = [("escape", "app.pop_screen", "back")]

    def __init__(self, manifest: BuildManifest, budget: Budget) -> None:
        super().__init__()
        self.manifest = manifest
        self.budget = budget

    def compose(self) -> ComposeResult:
        app = cast(PhntmWizard, self.app)
        resolve_components(self.manifest.components, app.catalog)  # loud if invalid
        over = self.budget.used_gb > self.budget.capacity_gb
        total = max(self.budget.capacity_gb, self.budget.used_gb)
        persona = self.manifest.persona
        emoji = app.presets[persona.value].emoji
        yield Footer()
        with VerticalScroll(id="step"):
            yield Static(
                f"STEP 3/3 — {emoji} {app.presets[persona.value].label} · {self.manifest.tier} GB",
                classes="step-tag",
            )
            yield Static(f"[bold]Plan: {self.manifest.name}[/]", classes="title")
            yield ProgressBar(
                total=total,
                id="meter",
                classes=("over" if over else ""),
            )
            yield Static(
                f"{self.budget.used_gb:.2f} GB used of {self.budget.capacity_gb:.2f} GB usable "
                f"({self.budget.utilization:.0%})",
                id="used",
            )
            yield Static(format_budget(self.budget), id="budget")
            yield Static(self._device_hint(), id="hint")
            yield Input(
                placeholder="save as (Enter = phntm-manifest.json)",
                id="out",
            )
            with Horizontal(id="saveline"):
                yield Button("← Back", id="back")
                yield Button("💾 Save manifest", id="save", variant="primary")
                yield Button("Finish", id="done")

    def on_mount(self) -> None:
        self.query_one("#meter", ProgressBar).progress = self.budget.used_gb

    def _device_hint(self) -> str:
        try:
            from .engine.devices import scan_devices

            sticks = scan_devices()
        except Exception:
            sticks = []
        if not sticks:
            return ("No USB stick detected right now — save the plan, plug one in, "
                    "then: [bold]phntm build <file> -d auto[/]")
        names = ", ".join(f"{s.path} ({s.human_size()})" for s in sticks)
        return f"Sticks ready: {names} — then [bold]phntm build <file> -d auto[/]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "back":
            self.app.pop_screen()
        elif bid == "save":
            self._save_manifest()
        elif bid == "done":
            self.app.exit()

    def _save_manifest(self) -> None:
        out = self.query_one("#out", Input).value.strip() or "phntm-manifest.json"
        path = Path(out).expanduser().resolve()
        try:
            path.write_text(self.manifest.model_dump_json(indent=2) + "\n")
        except OSError as exc:
            self.app.notify(f"could not write {path}: {exc}", severity="error")
            return
        self.app.notify(f"wrote {path}")
        self.query_one("#hint", Static).update(
            f"[green]✔ manifest written to {path}[/]\n"
            f"  validate:  [bold]phntm manifest validate -f {out}[/]\n"
            f"  preview:   [bold]phntm build {out} --dry-run[/]\n"
            f"  build:     plug a stick, then [bold]phntm build {out} -d auto -y[/]"
        )


class PhntmWizard(App[None]):
    """PHNTM ghost protocol — build a legendary USB stick, guided."""

    TITLE = "PHNTM — ghost protocol"
    SUB_TITLE = f"build a legendary USB stick · v{VERSION}"
    CSS = CSS

    def __init__(self, state: WizardState | None = None) -> None:
        super().__init__()
        self.state = state if state is not None else WizardState()
        self.presets = load_presets()
        self.catalog = load_catalog()

    def on_mount(self) -> None:
        self.push_screen(PersonaScreen())


def run_wizard() -> None:
    """Entry point used by ``phntm tui``."""
    PhntmWizard().run()


if __name__ == "__main__":
    run_wizard()