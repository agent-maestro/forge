"""Independently verify a transparency-log inclusion proof.

Usage:

    python tools/cli/zk_log_verify.py --leaf-hash sha256:abc... \\
        --log-url http://localhost:3010/api/log

    python tools/cli/zk_log_verify.py --index 0 \\
        --log-url https://api.monogate.dev/log

The verifier:

  1. Fetches the inclusion proof for the given leaf.
  2. Recomputes the Merkle root locally from
     `leaf + audit_path + index + tree_size` (no trust in the log).
  3. Compares against the ``root_hash`` in the published Signed
     Tree Head.

Exits 0 on PASS, 1 on FAIL with a one-line reason. Self-contained —
no external dependencies beyond Python stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from typing import Optional


# ── RFC 6962 hash primitives ────────────────────────────────────


def _sha256_hex(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _hex_only(h: str) -> str:
    return h[len("sha256:") :] if h.startswith("sha256:") else h


def _node_hash(left: str, right: str) -> str:
    payload = b"\x01" + bytes.fromhex(_hex_only(left)) + bytes.fromhex(_hex_only(right))
    return _sha256_hex(payload)


def _verify_inclusion(
    *,
    leaf: str,
    index: int,
    tree_size: int,
    audit_path: list[str],
    expected_root: str,
) -> tuple[bool, str]:
    """RFC 6962 §2.1.1 inclusion-proof verifier."""
    if index < 0 or index >= tree_size:
        return False, f"index {index} out of range for tree size {tree_size}"
    h = leaf
    fn = index
    sn = tree_size - 1
    pi = 0
    while sn > 0:
        if pi >= len(audit_path):
            return False, "audit path exhausted before reaching root"
        if fn % 2 == 1 or fn == sn:
            h = _node_hash(audit_path[pi], h)
            while fn % 2 == 0 and fn != 0:
                fn //= 2
                sn //= 2
        else:
            h = _node_hash(h, audit_path[pi])
        pi += 1
        fn //= 2
        sn //= 2
    if pi != len(audit_path):
        return False, f"audit path has {len(audit_path) - pi} extra unused entries"
    if h != expected_root:
        return False, (
            f"recomputed root {h[:30]}… does not match published root "
            f"{expected_root[:30]}…"
        )
    return True, "ok"


# ── Main ────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zk_log_verify",
        description=(
            "Verify a Verification Network transparency-log "
            "inclusion proof. Recomputes the root locally — no "
            "trust in the log operator."
        ),
    )
    parser.add_argument("--log-url", required=True,
                        help="Base URL of the log API (e.g. "
                             "http://localhost:3010/api/log).")
    parser.add_argument("--leaf-hash",
                        help="Leaf hash to look up. Mutually "
                             "exclusive with --index.")
    parser.add_argument("--index", type=int,
                        help="Leaf index to look up. Mutually "
                             "exclusive with --leaf-hash.")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only PASS / FAIL.")
    args = parser.parse_args(argv)

    if (args.leaf_hash is None) == (args.index is None):
        parser.error("pass exactly one of --leaf-hash / --index")

    base = args.log_url.rstrip("/")
    if args.leaf_hash:
        url = f"{base}/proof?leaf_hash={args.leaf_hash}"
        ident = f"leaf_hash={args.leaf_hash[:30]}…"
    else:
        url = f"{base}/proof?index={args.index}"
        ident = f"index={args.index}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"FAIL — log returned HTTP {e.code} {e.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"FAIL — could not reach log: {e.reason}", file=sys.stderr)
        return 1

    if not payload.get("ok"):
        print(f"FAIL — log error: {payload.get('error')}", file=sys.stderr)
        return 1

    leaf = payload["leaf_hash"]
    index = payload["leaf_index"]
    tree_size = payload["tree_size"]
    root = payload["root_hash"]
    audit_path = payload["audit_path"]
    sth = payload["sth"]

    ok, reason = _verify_inclusion(
        leaf=leaf,
        index=index,
        tree_size=tree_size,
        audit_path=audit_path,
        expected_root=root,
    )

    if ok:
        if not args.quiet:
            print(f"PASS — {ident}")
            print(f"  leaf:       {leaf}")
            print(f"  index:      {index}")
            print(f"  tree_size:  {tree_size}")
            print(f"  root:       {root}")
            print(f"  head_hash:  {sth['head_hash']}")
            print(f"  timestamp:  {sth['timestamp']}")
            print(f"  audit_path: {len(audit_path)} sibling(s)")
        else:
            print("PASS")
        return 0
    print(f"FAIL — {ident}: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
