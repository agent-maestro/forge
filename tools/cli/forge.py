"""Top-level Forge command surface."""

from __future__ import annotations

import argparse
from pathlib import Path


def _rescue_suite(args: argparse.Namespace) -> int:
    from tools.proof_carrying_rescue_replay import replay_manifest
    from tools.proof_carrying_rescue_suite import (
        build_approval_gate,
        build_obligation_registry,
        run_suite,
        validate_strict,
        write_approval_gate,
        write_explorer_fixture,
        write_obligation_registry,
        write_outputs,
    )

    manifest = run_suite()
    registry = build_obligation_registry(manifest)
    manifest["obligation_registry"] = registry
    replay = replay_manifest(manifest)
    approval = build_approval_gate(manifest, replay, registry)
    manifest["approval_gate"] = approval

    write_outputs(manifest, args.manifest_json, args.markdown)
    args.replay_json.parent.mkdir(parents=True, exist_ok=True)
    args.replay_json.write_text(args.json_dumps(replay), encoding="utf-8")
    write_explorer_fixture(manifest, replay, args.explorer_json)
    write_obligation_registry(registry, args.registry_json)
    write_approval_gate(approval, args.approval_json)

    if args.strict:
        validate_strict(manifest)
        if not replay["valid"]:
            raise SystemExit("PROOF_CARRYING_RESCUE_REPLAY_FAILED")

    print(f"Wrote {args.manifest_json}")
    print(f"Wrote {args.replay_json}")
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.explorer_json}")
    print(f"Wrote {args.registry_json}")
    print(f"Wrote {args.approval_json}")
    print("FORGE_RESCUE_SUITE_OK")
    return 0


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Monogate Forge research and compiler command surface.",
    )
    subcommands = parser.add_subparsers(dest="command")

    rescue = subcommands.add_parser(
        "rescue",
        description="Emit proof-carrying rescue research artifacts.",
    )
    rescue.add_argument(
        "--suite",
        action="store_true",
        help="Emit the proof-carrying rescue suite v0 bundle.",
    )
    rescue.add_argument(
        "--strict",
        action="store_true",
        help="Validate the suite and replay contract before exiting.",
    )
    rescue.add_argument(
        "--manifest-json",
        type=Path,
        default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.json"),
    )
    rescue.add_argument(
        "--replay-json",
        type=Path,
        default=Path("reports/proof_carrying_rescue_replay_v0_2026_05_26.json"),
    )
    rescue.add_argument(
        "--markdown",
        type=Path,
        default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.md"),
    )
    rescue.add_argument(
        "--explorer-json",
        type=Path,
        default=Path("reports/proof_carrying_rescue_explorer_fixture_v0_2026_05_26.json"),
    )
    rescue.add_argument(
        "--registry-json",
        type=Path,
        default=Path("reports/rescue_obligation_registry_v0_2026_05_26.json"),
    )
    rescue.add_argument(
        "--approval-json",
        type=Path,
        default=Path("reports/rescue_artifact_approval_v0_2026_05_26.json"),
    )
    rescue.set_defaults(handler=_rescue_suite, json_dumps=_json_dumps)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    if args.command == "rescue" and not args.suite:
        parser.error("forge rescue currently requires --suite")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
