<p align="right"><a href="README.md">中文</a> | <strong>English</strong></p>

# rgame

A top-down, single-screen roguelite for Windows, Android, and iOS, featuring automatic attacks, a three-weapon cycle, three-stage mode, and endless mode.

## Overview

This repository turns the RGame design brief into an engineering-oriented Python project:

- **Core library:** rules, state machines, damage, enemies, drafting, drops, achievements, saves, and logs live in `rgame/`. It has no GUI dependency and can be tested independently.
- **Renderer A — pygame:** `rgame/render/pygame_app.py`, the default desktop renderer for Windows, macOS, and Linux.
- **Renderer B — Kivy:** `rgame/render/kivy_app.py`, designed for landscape mobile play with touch and a virtual joystick; it can also run on desktop.
- **Build and release:** use Buildozer for Android on Linux/macOS and kivy-ios for iOS on macOS. Visual and audio requirements are documented in [VISUAL_AUDIO_REQUIREMENTS.md](VISUAL_AUDIO_REQUIREMENTS.md).

## Install and run

```bash
# Dependencies
pip install pygame "kivy[base]" pytest

# Default pygame desktop client
python main.py --seed 42

# Kivy client
python main.py --backend kivy --platform android

# Headless engine check
python main.py --headless

# Tests
python -m pytest -q
```

## Gameplay

1. Choose three-stage or endless mode from the main menu.
2. Select one of three starting forms.
3. Move with the keyboard, touch, or virtual joystick while attacks fire automatically.
4. Cycle through three weapons and combine upgrades from level-up drafts.
5. Defeat enemies, collect drops, unlock achievements, and preserve progress through saves.

## Project layout

| Path | Purpose |
| --- | --- |
| `rgame/core/` | Engine rules, combat state, entities, and progression |
| `rgame/render/` | pygame and Kivy presentation layers |
| `rgame/assets/` | Packaged images, audio, and other runtime media |
| `VISUAL_AUDIO_REQUIREMENTS.md` | Visual and audio asset requirements |
| `tests/` | Automated engine smoke coverage |
| `main.py` | Unified desktop, mobile, and headless entry point |

The Python package explicitly includes `rgame/assets/**/*`, so wheels installed from a build contain the same runtime media as a source checkout.

## Testing and packaging

CI performs the following checks:

- Python bytecode compilation.
- Engine smoke tests.
- Headless launch from source.
- Source distribution and wheel build.
- Verification that key image and audio assets exist in the wheel.
- Installation of the wheel followed by a headless launch through the installed `rgame` command.

## Known boundaries

- Interactive rendering, physical input devices, and full audio behavior still require manual device testing.
- Android builds require a Linux/macOS Buildozer host.
- iOS builds require macOS, Xcode, and kivy-ios.
- Automated coverage currently emphasizes engine startup and packaging rather than a complete battle playthrough.
