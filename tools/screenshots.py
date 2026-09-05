"""Regenerate every screenshot in brand/screens/ — real terminal captures.

How it works
------------
* CLI shots:  spawn ``python -m phntm <args>`` inside a real PTY and replay the
  exact bytes through pyte (a virtual terminal). What you see is byte-for-byte
  what a user's terminal shows — colors, box-drawing, typer help, all of it.
* TUI shots:  drive ``PhntmWizard`` headlessly (Textual ``run_test``) and use
  Textual's native ``save_screenshot`` (SVG), then rasterize with ImageMagick.
* Both convert to PNG via the ``magick``/``convert`` binary.

Run from the repo root:  python tools/screenshots.py
"""

from __future__ import annotations

import os
import pty
import subprocess
import sys
from pathlib import Path

import pyte

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "screens"
PY = sys.executable

# ---------------------------------------------------------------- CLI via PTY


def run_pty(argv: list[str], cols: int = 115, lines: int = 34) -> tuple[str, int]:
    """Run a command in a pty; return (rendered_text, exit_code)."""
    screen = pyte.Screen(cols, lines)
    stream = pyte.ByteStream(screen)
    master, slave = pty.openpty()
    child = subprocess.Popen(
        [PY, "-m", "phntm", *argv],
        stdout=slave, stderr=slave, stdin=subprocess.DEVNULL,
        cwd=str(ROOT),
    )
    os.close(slave)
    try:
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            stream.feed(chunk)
        child.wait(timeout=30)
    finally:
        os.close(master)
    code = child.returncode if child.returncode is not None else -1
    # render the virtual screen, trimming trailing blank lines
    text = "\n".join(line.rstrip() for line in screen.display).rstrip("\n")
    return text, code


def save_text(name: str, text: str, title: str) -> None:
    """Render captured terminal text as a nice SVG + PNG (monospace, dark)."""
    svg = _text_svg(title, text)
    _write(svg, name, ".svg")
    _rasterize(name)


def _text_svg(title: str, text: str) -> str:
    lines = text.splitlines()
    line_h = 20
    pad = 18
    width = 1180
    height = pad * 2 + len(lines) * line_h + 34
    esc_title = title.replace("&", "&amp;").replace("<", "&lt;")
    esc_lines = [
        l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for l in lines
    ]
    body = "\n".join(
        f'<text x="{pad}" y="{pad + 34 + i * line_h}" font-family="DejaVu Sans Mono,monospace" '
        f'font-size="15" fill="#c9d1d9">{l or "&#160;"}</text>'
        for i, l in enumerate(esc_lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="#0d1117"/>
<rect x="{pad-10}" y="{pad}" width="{width-2*pad+20}" height="{34}" fill="#161b22" rx="7"/>
<text x="{pad+6}" y="{pad+23}" font-family="DejaVu Sans,monospace" font-size="16" font-weight="bold" fill="#58a6ff">{esc_title}</text>
{body}
</svg>"""


# ---------------------------------------------------------------- TUI


def tui_shots() -> None:
    import asyncio

    from phntm.models import Persona
    from phntm.tui import PhntmWizard
    from textual.widgets import Button, RadioButton, RadioSet

    async def walk() -> None:
        app = PhntmWizard()
        async with app.run_test(size=(118, 34)) as pilot:
            app.save_screenshot(str(OUT / "raw-tui-persona.svg"))
            # --- step 1: pick the PENTEST persona
            radios = app.screen.query(RadioButton)
            await pilot.click(radios[1])
            await pilot.click("#next")
            await pilot.pause()
            app.save_screenshot(str(OUT / "raw-tui-tier.svg"))
            # --- step 2: pick 32 GB
            radios = app.screen.query(RadioButton)
            await pilot.click(radios[1])
            await pilot.click("#next")
            await pilot.pause()
            app.save_screenshot(str(OUT / "raw-tui-components.svg"))
            # --- step 3: straight to the plan
            await pilot.click("#next")
            await pilot.pause()
            app.save_screenshot(str(OUT / "raw-tui-plan.svg"))

    asyncio.run(walk())


def _write(svg: str, name: str, ext: str) -> None:
    (OUT / f"{name}{ext}").write_text(svg)


def _rasterize(name: str) -> None:
    subprocess.run(
        ["magick", "convert", "-density", "150", str(OUT / f"{name}.svg"), str(OUT / f"{name}.png")],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------- main


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # clean old raw files
    for old in OUT.glob("*.svg"):
        if old.name.startswith("raw-"):
            old.unlink()

    # --- CLI gallery (authentic PTY bytes)
    shots: list[tuple[str, list[str], str]] = [
        ("cli-help", ["help"], "phntm help — the whole workflow on one screen"),
        ("cli-presets", ["presets"], "phntm presets — persona × tier matrix (14)"),
        ("cli-components", ["components"], "phntm components — browse the 25-component catalog"),
        ("cli-components-direct", ["components", "--direct"], "phntm components --direct — only components with a download link"),
        ("cli-doctor", ["doctor"], "phntm doctor — is this machine ready to build sticks?"),
        ("cli-manifest-plan", ["build", "--dry-run", "examples/dfir-spectre-32.json"], "phntm build --dry-run — full plan, zero side effects"),
        ("cli-cache", ["cache"], "phntm cache — the offline arsenal store"),
        ("cli-status", ["status", "/tmp/phntm-demo-stick"], "phntm status — refuses non-sticks cleanly"),
        ("cli-version", ["--version"], "phntm --version"),
    ]
    for name, argv, title in shots:
        text, code = run_pty(argv)
        # mark the exit code on the shot so the review is honest
        save_text(name, text, f"{title}  ·  exit {code}")

    # fake a built stick so "status" shows real metadata
    demo = Path("/tmp/phntm-demo-stick")
    demo.mkdir(exist_ok=True)
    subprocess.run(
        [PY, "-c",
         "from phntm.catalog import load_catalog; from phntm.engine.build import metadata_for;"
         "from phntm.engine.metadata import write_metadata;"
         "from phntm.presets import manifest_from_preset; from phntm.models import Persona;"
         "write_metadata('/tmp/phntm-demo-stick', metadata_for(manifest_from_preset(Persona.DFIR, 32), load_catalog()))"],
        cwd=str(ROOT), check=True,
    )
    text, code = run_pty(["status", "/tmp/phntm-demo-stick"])
    save_text("cli-status-stick", text, f"phntm status /tmp/phntm-demo-stick  ·  exit {code}")

    # --- TUI gallery (headless Textual)
    tui_shots()
    for svg in sorted(OUT.glob("raw-tui-*.svg")):
        png = svg.with_suffix(".png")
        subprocess.run(
            ["magick", "convert", "-density", "150", str(svg), str(png)],
            check=True, capture_output=True,
        )

    print(f"wrote screenshots to {OUT}/")


if __name__ == "__main__":
    main()