from pathlib import Path

from tools.cli.forge import main


def test_forge_rescue_suite_emits_bundle(tmp_path: Path):
    manifest = tmp_path / "suite.json"
    replay = tmp_path / "replay.json"
    markdown = tmp_path / "suite.md"
    explorer = tmp_path / "explorer.json"
    registry = tmp_path / "registry.json"
    approval = tmp_path / "approval.json"

    result = main(
        [
            "rescue",
            "--suite",
            "--strict",
            "--manifest-json",
            str(manifest),
            "--replay-json",
            str(replay),
            "--markdown",
            str(markdown),
            "--explorer-json",
            str(explorer),
            "--registry-json",
            str(registry),
            "--approval-json",
            str(approval),
        ]
    )

    assert result == 0
    assert manifest.exists()
    assert replay.exists()
    assert markdown.exists()
    assert explorer.exists()
    assert registry.exists()
    assert approval.exists()
    assert (
        "monogate.dev.rescue_suite_explorer_fixture.v0"
        in explorer.read_text(encoding="utf-8")
    )
    assert "guard_clamp_output_safety_witness_discharges_concrete_obligation" in registry.read_text(encoding="utf-8")
    assert "saturation_deshelf_clamp_witness_discharges_concrete_obligation" in registry.read_text(encoding="utf-8")
    assert "approved_for_existing_public_surfaces" in approval.read_text(encoding="utf-8")
