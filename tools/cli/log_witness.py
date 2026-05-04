"""Transparency-log witness client.

A witness is the auditing half of a transparency log: an
independent process that polls the log's Signed Tree Heads, keeps a
local history, and screams when it sees evidence the log operator
rewrote the past. RFC 6962 Certificate Transparency calls these
"monitors" / "witnesses"; the same role applies to the Verification
Network log.

What this client does on every poll:

  1. Fetches the current STH from ``/api/log/sth``.
  2. Verifies the operator's Ed25519 signature against the public
     key (fetched + pinned on first run).
  3. If we've seen a previous STH, fetches a *consistency proof*
     between old.tree_size and new.tree_size and verifies it
     locally — a single failure is non-repudiable evidence the log
     either dropped, reordered, or rewrote entries.
  4. Appends the new STH to a local history file. The history is
     append-only by design; an auditor can replay it at any time.

Usage:

    # Run forever, polling every 30 s, storing history in ./witness.log
    python tools/cli/log_witness.py --log-url http://localhost:3010/api/log

    # Poll N times then exit (useful for CI smoke tests)
    python tools/cli/log_witness.py --log-url ... --max-iters 6

    # Pin a specific operator key — refuse to follow a key rotation
    python tools/cli/log_witness.py --log-url ... \\
        --pin-key-id 7c6c...

If anything fails — signature mismatch, consistency-proof failure,
key-rotation surprise, log unreachable for too long — the client
exits non-zero with a one-line PASS/FAIL summary. Designed to be
embedded behind ``cron`` / a systemd timer / ``kubectl run --restart=OnFailure``.

Self-contained: stdlib only (the Ed25519 verifier lives next to
this script in `_ed25519_verify.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ed25519_verify import verify as _ed25519_verify


# ── RFC 6962 hash primitives (mirrored from zk_log_verify.py) ───


import hashlib

_LEAF_PREFIX = b"\x00"
_INTERNAL_PREFIX = b"\x01"


def _sha256_hex(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _hex_only(h: str) -> str:
    return h[len("sha256:"):] if h.startswith("sha256:") else h


def _node_hash(left: str, right: str) -> str:
    return _sha256_hex(
        _INTERNAL_PREFIX + bytes.fromhex(_hex_only(left)) + bytes.fromhex(_hex_only(right))
    )


# ── RFC 6962 §2.1.2 consistency-proof verifier ──────────────────


def _verify_consistency(
    *,
    old_root: str,
    old_size: int,
    new_root: str,
    new_size: int,
    proof: list[str],
) -> tuple[bool, str]:
    """Mirrors `verifyConsistency` from command-center/lib/merkle-log.ts."""
    if old_size < 0 or new_size < old_size:
        return False, f"bad sizes old={old_size} new={new_size}"
    if old_size == 0:
        if proof:
            return False, "expected empty proof for old_size=0"
        return True, "ok"
    if old_size == new_size:
        if proof:
            return False, "expected empty proof when sizes match"
        if old_root != new_root:
            return False, "sizes match but roots differ"
        return True, "ok"
    if not proof:
        return False, "consistency proof unexpectedly empty"

    p = list(proof)
    fn = old_size - 1
    sn = new_size - 1
    while fn % 2 == 1:
        fn //= 2
        sn //= 2
    if fn == 0:
        fr = old_root
        sr = old_root
    else:
        if not p:
            return False, "ran out of proof at first step"
        fr = p.pop(0)
        sr = fr
    while fn != 0:
        if not p:
            return False, "ran out of proof mid-walk"
        if fn % 2 == 1 or fn == sn:
            c = p.pop(0)
            fr = _node_hash(c, fr)
            sr = _node_hash(c, sr)
            while fn % 2 == 0:
                fn //= 2
                sn //= 2
        else:
            c = p.pop(0)
            sr = _node_hash(sr, c)
        fn //= 2
        sn //= 2
    while sn != 0:
        if not p:
            return False, "ran out of proof during sn-only descent"
        c = p.pop(0)
        sr = _node_hash(sr, c)
        sn //= 2
    if p:
        return False, f"unused proof entries: {len(p)}"
    if fr != old_root:
        return False, f"recomputed old root {fr[:30]}… ≠ stored {old_root[:30]}…"
    if sr != new_root:
        return False, f"recomputed new root {sr[:30]}… ≠ published {new_root[:30]}…"
    return True, "ok"


# ── HTTP helpers ────────────────────────────────────────────────


class WitnessError(Exception):
    pass


def _fetch_json(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise WitnessError(f"GET {url} → HTTP {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise WitnessError(f"GET {url} unreachable: {e.reason}") from e


# ── Signature ───────────────────────────────────────────────────


def _verify_signature(sth: dict, public_key_hex: str) -> tuple[bool, str]:
    sig = sth.get("signature") or ""
    payload = sth.get("signed_payload") or ""
    if not sig:
        return False, "STH has no signature"
    if not sig.startswith("ed25519:"):
        return False, f"unsupported signature suite {sig[:24]}…"
    if not payload:
        return False, "STH has no signed_payload"
    try:
        pk = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(sig[len("ed25519:"):])
    except ValueError as e:
        return False, f"could not decode hex: {e}"
    try:
        ok = _ed25519_verify(pk, payload.encode("utf-8"), sig_bytes)
    except ValueError as e:
        return False, f"signature verify crashed: {e}"
    if not ok:
        return False, "signature does not validate"
    return True, "ok"


# ── Witness state ───────────────────────────────────────────────


@dataclass
class WitnessState:
    public_key_hex: str
    key_id: str
    last_sth: Optional[dict[str, Any]] = None


def _load_state(history_path: Path,
                pin_key_id: Optional[str],
                log_base: str) -> WitnessState:
    """If we've polled before, restore the last STH and the key. Else
    fetch the operator key fresh and pin it (or honour --pin-key-id)."""
    if history_path.exists() and history_path.stat().st_size > 0:
        last = None
        with history_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                last = json.loads(line)
        if last is not None and "operator_key" in last:
            key = last["operator_key"]
            sth = last.get("sth")
            if pin_key_id and key.get("key_id") != pin_key_id:
                raise WitnessError(
                    f"history was signed by key_id {key.get('key_id')} "
                    f"but --pin-key-id requires {pin_key_id}"
                )
            return WitnessState(
                public_key_hex=key["raw_hex"],
                key_id=key["key_id"],
                last_sth=sth,
            )

    pk_url = log_base + "/public-key"
    info = _fetch_json(pk_url)
    if not info.get("ok"):
        raise WitnessError(f"public-key endpoint error: {info}")
    if info.get("algorithm") != "ed25519":
        raise WitnessError(f"unsupported key algorithm: {info.get('algorithm')}")
    if pin_key_id and info["key_id"] != pin_key_id:
        raise WitnessError(
            f"operator key_id {info['key_id']} ≠ pinned {pin_key_id}"
        )
    return WitnessState(
        public_key_hex=info["raw_hex"],
        key_id=info["key_id"],
        last_sth=None,
    )


def _append_history(history_path: Path,
                    state: WitnessState,
                    sth: dict[str, Any],
                    notes: list[str]) -> None:
    record = {
        "polled_at": _utcnow_iso(),
        "sth":       sth,
        "operator_key": {
            "key_id":  state.key_id,
            "raw_hex": state.public_key_hex,
        },
        "notes": notes,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── One poll ────────────────────────────────────────────────────


def _poll_once(state: WitnessState, log_base: str) -> tuple[dict, list[str]]:
    """Fetch + verify one STH against `state`. Returns the new STH
    plus a list of human-readable notes for the history record.

    Raises :class:`WitnessError` on any verification failure — the
    caller logs it and exits non-zero."""
    notes: list[str] = []
    new_sth = _fetch_json(log_base + "/sth").get("sth")
    if not isinstance(new_sth, dict):
        raise WitnessError(f"unexpected /sth response shape: {new_sth!r}")

    sig_ok, sig_reason = _verify_signature(new_sth, state.public_key_hex)
    if not sig_ok:
        raise WitnessError(f"signature: {sig_reason}")
    notes.append(f"signature ok (key_id={state.key_id[:12]}…)")

    if state.last_sth is None:
        notes.append("first observation — no consistency proof needed")
        return new_sth, notes

    old_size = int(state.last_sth["tree_size"])
    new_size = int(new_sth["tree_size"])
    if new_size < old_size:
        raise WitnessError(
            f"tree_size went backwards: {new_size} < {old_size} — "
            "log operator dropped or rewrote entries"
        )
    if new_size == old_size:
        if state.last_sth["root_hash"] != new_sth["root_hash"]:
            raise WitnessError(
                "tree_size unchanged but root_hash changed — "
                "fork: same height, different content"
            )
        notes.append(f"unchanged at size {new_size}")
        return new_sth, notes

    cp_url = f"{log_base}/consistency?from={old_size}&to={new_size}"
    cp = _fetch_json(cp_url)
    if not cp.get("ok"):
        raise WitnessError(f"consistency endpoint returned error: {cp}")
    cons_ok, cons_reason = _verify_consistency(
        old_root=state.last_sth["root_hash"],
        old_size=old_size,
        new_root=new_sth["root_hash"],
        new_size=new_size,
        proof=cp.get("proof", []),
    )
    if not cons_ok:
        raise WitnessError(
            f"consistency proof from {old_size} → {new_size} failed: "
            f"{cons_reason} — log rewrote history"
        )
    notes.append(
        f"consistency ok ({old_size} → {new_size}, "
        f"{len(cp['proof'])} sibling(s))"
    )
    return new_sth, notes


# ── Main loop ───────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="log_witness",
        description=(
            "Independent transparency-log witness — polls the STH, "
            "verifies signatures, checks consistency between heads, "
            "appends an audit history."
        ),
    )
    parser.add_argument(
        "--log-url", required=True,
        help="Log API base URL, e.g. http://localhost:3010/api/log",
    )
    parser.add_argument(
        "--history", type=Path, default=Path("witness.log"),
        help="Append-only JSONL file recording every poll. "
             "Default: ./witness.log",
    )
    parser.add_argument(
        "--interval", type=float, default=30.0,
        help="Seconds between polls. Default 30.",
    )
    parser.add_argument(
        "--max-iters", type=int, default=-1,
        help="Stop after N polls. Default -1 (run forever).",
    )
    parser.add_argument(
        "--pin-key-id",
        help="Refuse if the operator's key_id doesn't match this hex "
             "string. The first poll otherwise pins automatically.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print only PASS / FAIL per poll.",
    )
    args = parser.parse_args(argv)

    base = args.log_url.rstrip("/")

    try:
        state = _load_state(args.history, args.pin_key_id, base)
    except WitnessError as e:
        print(f"FAIL — startup: {e}", file=sys.stderr)
        return 1

    print(
        f"witness pinned to key_id {state.key_id} "
        f"(history at {args.history.resolve()})",
        file=sys.stderr,
    )

    n = 0
    while args.max_iters == -1 or n < args.max_iters:
        n += 1
        try:
            new_sth, notes = _poll_once(state, base)
        except WitnessError as e:
            print(f"FAIL — poll {n}: {e}")
            _append_history(args.history, state,
                            sth={"error": str(e)},
                            notes=[f"FAIL: {e}"])
            return 1

        _append_history(args.history, state, new_sth, notes)
        state.last_sth = new_sth
        if args.quiet:
            print(f"PASS poll={n} size={new_sth['tree_size']}")
        else:
            print(
                f"[{_utcnow_iso()}] poll {n}: "
                f"size={new_sth['tree_size']} "
                f"root={new_sth['root_hash'][:30]}… "
                f"({'; '.join(notes)})"
            )

        if args.max_iters != -1 and n >= args.max_iters:
            break
        time.sleep(args.interval)

    print(f"\ndone; {n} poll(s); witness history at {args.history.resolve()}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
