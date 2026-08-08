"""CI smoke coverage for the headless engine path."""

from rgame.engine import Engine


def test_engine_starts_balanced_run_with_stable_seed() -> None:
    engine = Engine(platform="linux", seed=1234)

    engine.start_run(preset_id="preset_balanced")

    assert engine.state() == "RUNNING"
    assert engine.seed == 1234
