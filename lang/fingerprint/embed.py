"""Embed a computation fingerprint into a backend's emitted source.

Every backend can opt in by routing its final source string through
:func:`embed_fingerprint` before writing it to disk. The embedding
prepends a small, language-appropriate comment block carrying the
module hash and per-function tree hashes — readable by humans and
greppable by tools.

The format is intentionally minimal:

    <comment-prefix> ── monogate-fingerprint/v1 ──
    <comment-prefix> module:      sha256:abcd…
    <comment-prefix> source:      gaussian.eml
    <comment-prefix> spec:        monogate-fingerprint/v1
    <comment-prefix>
    <comment-prefix> functions:
    <comment-prefix>   gaussian   tree=sha256:1234… chain=1 drift=low
    <comment-prefix>   …
    <comment-prefix> ──

We deliberately avoid dumping the full JSON inline. Backends that
need the full document point at the sidecar `.fp.json` file Forge
writes alongside the output.
"""

from __future__ import annotations

from .compute import ModuleFingerprint


# Map every Forge backend target to the comment-prefix the language
# uses for line comments. Targets that have no line-comment syntax
# (or where embedding makes no sense — pure binary outputs etc.)
# are absent and round-trip through the embedder unchanged.
_COMMENT_PREFIX = {
    # C-family
    "c":             "//",
    "cpp":           "//",
    "rust":          "//",
    "java":          "//",
    "kotlin":        "//",
    "csharp":        "//",
    "javascript":    "//",
    "swift":         "//",
    "go":            "//",
    "solidity":      "//",
    "luau":          "--",
    "ada":           "--",
    "vhdl":          "--",
    "verilog":       "//",
    "systemverilog": "//",
    "chisel":        "//",
    # GPU / shading
    "hlsl":          "//",
    "glsl":          "//",
    "glsles":        "//",
    "wgsl":          "//",
    "metal":         "//",
    # Scripting / data
    "python":        "#",
    "matlab":        "%",
    "ros2":          "#",
    "gdscript":      "#",
    "autosar":       "//",
    "aadl":          "--",
    # Formal
    "lean":          "--",
    "coq":           "(*",   # block comment open — closed below
    "isabelle":      "(*",
    # Lower-level
    "llvm":          ";",
    "wasm":          ";;",
}


def has_embed_support(target: str) -> bool:
    """Return True iff Forge can stamp a fingerprint into this target's
    source. Pure-binary outputs (none today) would return False."""
    return target in _COMMENT_PREFIX


def embed_fingerprint(
    source: str,
    *,
    target: str,
    fp: ModuleFingerprint,
) -> str:
    """Return ``source`` with a fingerprint comment block prepended.

    Pass-through (returns ``source`` unchanged) if the target doesn't
    have a comment-prefix mapping. Idempotent: running this twice
    over the same source produces a second header — backends are
    expected to call it exactly once, immediately before writing.
    """
    prefix = _COMMENT_PREFIX.get(target)
    if prefix is None:
        return source

    # Coq / Isabelle use `(* … *)` block comments; we stay out of
    # the line-prefix world for them.
    if prefix == "(*":
        return _wrap_block_comment(source, fp)

    return _wrap_line_comments(source, prefix, fp)


# ── Internal helpers ────────────────────────────────────────────────


def _wrap_line_comments(
    source: str,
    prefix: str,
    fp: ModuleFingerprint,
) -> str:
    body = _format_lines(fp)
    header_lines = [f"{prefix} {line}".rstrip() for line in body]
    # One blank line between the fingerprint block and the source so
    # downstream tooling can still reliably find the first declaration.
    header = "\n".join(header_lines) + "\n\n"
    # Preserve any leading shebang / pragma line. If the source starts
    # with `#!`, keep it on top.
    if source.startswith("#!"):
        nl = source.find("\n")
        if nl == -1:
            return source + "\n" + header
        return source[: nl + 1] + header + source[nl + 1 :]
    return header + source


def _wrap_block_comment(source: str, fp: ModuleFingerprint) -> str:
    body = _format_lines(fp)
    inner = "\n  ".join(body)
    header = f"(*\n  {inner}\n*)\n\n"
    return header + source


def _format_lines(fp: ModuleFingerprint) -> list[str]:
    out: list[str] = []
    out.append("── monogate-fingerprint/v1 ──")
    out.append(f"module: {fp.module_hash}")
    out.append(f"name:   {fp.module.get('name') or '(unnamed)'}")
    src = fp.module.get("source_file") or "(inline)"
    out.append(f"source: {src}")
    out.append(f"spec:   {fp.spec}  schema={fp.version}")
    out.append("")
    out.append("functions:")
    for fn in fp.functions:
        chain = fn.profile.get("chain_order", "?")
        drift = fn.profile.get("fp16_drift_risk", "?")
        nodes = fn.profile.get("node_count", "?")
        out.append(
            f"  {fn.name}  tree={fn.tree_hash} chain={chain} "
            f"drift={drift} nodes={nodes}"
        )
        if fn.verify_hash:
            out.append(f"    verify={fn.verify_hash}")
        if fn.shape_class_id is not None:
            out.append(f"    shape_class={fn.shape_class_id}")
        if fn.machlib_cert_hash:
            out.append(f"    machlib={fn.machlib_cert_hash}")
    out.append("")
    out.append("Verify this fingerprint:")
    out.append("  eml-compile <source.eml> --emit-fingerprint")
    out.append("──")
    return out
