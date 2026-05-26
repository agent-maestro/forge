from pathlib import Path

from tools.cli.forge import main


def test_forge_rescue_suite_emits_bundle(tmp_path: Path):
    manifest = tmp_path / "suite.json"
    replay = tmp_path / "replay.json"
    markdown = tmp_path / "suite.md"
    explorer = tmp_path / "explorer.json"

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
        ]
    )

    assert result == 0
    assert manifest.exists()
    assert replay.exists()
    assert markdown.exists()
    assert explorer.exists()
    assert (
        "monogate.dev.rescue_suite_explorer_fixture.v0"
        in explorer.read_text(encoding="utf-8")
    )
