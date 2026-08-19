"""Project-level contract tests for the local improvement baseline."""

from pathlib import Path

from rgame.config.content import load_default_bundle
from rgame.tools.verify_assets import main as verify_assets


ROOT = Path(__file__).resolve().parents[1]


def test_default_bundle_references_only_declared_content() -> None:
    bundle = load_default_bundle()

    assert len(bundle.weapons) >= 20
    assert len(bundle.enemies) >= 7
    assert len(bundle.stages) >= 6
    for stage in bundle.stages.values():
        assert set(stage["enemy_pool"]) <= set(bundle.enemies)
        assert len(stage["enemy_pool"]) == len(stage["enemy_weights"])


def test_asset_verifier_uses_repository_default_root() -> None:
    assert verify_assets(["--base", str(ROOT / "rgame" / "assets" / "v2"), "--quiet"]) == 0
