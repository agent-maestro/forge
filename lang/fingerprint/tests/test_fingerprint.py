"""Tests for the computation-fingerprinting library.

Anchors three contracts:

  * **Determinism** — same source produces the same fingerprint
    across multiple parses, on any machine.
  * **Tamper-evidence** — changing an operator, literal, parameter
    name, type, where-clause, or contract changes the fingerprint.
  * **Stability under cosmetic noise** — whitespace, comments, line
    numbers, and absolute file paths do *not* change the fingerprint.

The tests use the EMLModule loader directly (rather than the parser)
to keep them hermetic — fingerprint behaviour is independent of how
an AST got built.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


# Make the repo root importable for `from lang.parser ...`.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lang.fingerprint import (
    FINGERPRINT_SPEC,
    fingerprint_function,
    fingerprint_module,
    sha256_hex,
    canonicalize_function,
    canonicalize_node,
)
from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLImport,
    EMLModule,
    NodeKind,
    Param,
    WhereClause,
)


# ── AST builder helpers ────────────────────────────────────────────


def lit(value: float | int) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=value)


def var(name: str) -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=name)


def binop(op: str, l: ASTNode, r: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BINOP, value=op, children=[l, r])


def call_exp(arg: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.EXP, children=[arg])


def block(*stmts: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, children=list(stmts))


def make_gaussian_fn(*, name: str = "gaussian") -> EMLFunction:
    """Hand-rolled AST for a Gaussian — exp(-(x-mu)^2 / (2*sigma^2))."""
    x, mu, sigma = var("x"), var("mu"), var("sigma")
    dx_squared = binop("*", binop("-", x, mu), binop("-", x, mu))
    two_sigma_sq = binop("*", lit(2.0), binop("*", sigma, sigma))
    inner = binop("/", ASTNode(kind=NodeKind.UNARYOP, value="-",
                               children=[dx_squared]), two_sigma_sq)
    body = block(call_exp(inner))
    return EMLFunction(
        name=name,
        params=[Param(name="x", type_name="Real"),
                Param(name="mu", type_name="Real"),
                Param(name="sigma", type_name="Real")],
        return_type="Real",
        where_clauses=[WhereClause(kind="chain_order", op="<=", value=1)],
        body=body,
    )


def make_module(*, name: str = "demo", fns=None) -> EMLModule:
    return EMLModule(
        name=name,
        functions=list(fns or [make_gaussian_fn()]),
        source_file="gaussian.eml",
    )


# ── Determinism ────────────────────────────────────────────────────


def test_same_source_produces_same_module_hash() -> None:
    fp_a = fingerprint_module(make_module())
    fp_b = fingerprint_module(make_module())
    assert fp_a.module_hash == fp_b.module_hash
    assert [f.tree_hash for f in fp_a.functions] == [
        f.tree_hash for f in fp_b.functions
    ]


def test_module_hash_is_a_proper_sha256_string() -> None:
    fp = fingerprint_module(make_module())
    assert fp.module_hash.startswith("sha256:")
    assert len(fp.module_hash) == len("sha256:") + 64


def test_spec_string_matches_constant() -> None:
    fp = fingerprint_module(make_module())
    assert fp.spec == FINGERPRINT_SPEC


# ── Tamper-evidence ────────────────────────────────────────────────


def test_changing_operator_changes_tree_hash() -> None:
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    # Flip the outer multiply to an add — same shape, different math.
    fn.body.children[0].children[0].children[0].value = "+"  # exp -> "/" -> "*"
    mutated = fingerprint_module(make_module(fns=[fn])).functions[0].tree_hash
    assert base != mutated


def test_changing_literal_changes_tree_hash() -> None:
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    # Find the `2.0` constant inside `2.0 * sigma * sigma` and flip it.
    fn.body.children[0].children[0].children[1].children[0].value = 3.0
    mutated = fingerprint_module(make_module(fns=[fn])).functions[0].tree_hash
    assert base != mutated


def test_renaming_parameter_changes_tree_hash() -> None:
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    fn.params[0].name = "input"
    mutated = fingerprint_module(make_module(fns=[fn])).functions[0].tree_hash
    assert base != mutated


def test_changing_param_type_changes_tree_hash() -> None:
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    fn.params[0].type_name = "f32"
    mutated = fingerprint_module(make_module(fns=[fn])).functions[0].tree_hash
    assert base != mutated


def test_changing_chain_order_constraint_changes_tree_hash() -> None:
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    fn.where_clauses[0].value = 2
    mutated = fingerprint_module(make_module(fns=[fn])).functions[0].tree_hash
    assert base != mutated


def test_changing_function_name_changes_tree_hash() -> None:
    a = fingerprint_module(make_module(fns=[make_gaussian_fn(name="g1")]))
    b = fingerprint_module(make_module(fns=[make_gaussian_fn(name="g2")]))
    assert a.functions[0].tree_hash != b.functions[0].tree_hash


def test_adding_a_function_changes_module_hash() -> None:
    a = fingerprint_module(make_module())
    extra = EMLFunction(
        name="extra",
        params=[Param(name="x", type_name="Real")],
        return_type="Real",
        body=block(var("x")),
    )
    b = fingerprint_module(make_module(fns=[make_gaussian_fn(), extra]))
    assert a.module_hash != b.module_hash


def test_one_byte_change_to_a_constant_changes_module_hash() -> None:
    """The headline guarantee: any meaningful edit produces a different fingerprint."""
    base = fingerprint_module(make_module()).module_hash
    fn = make_gaussian_fn()
    # Swap 2.0 → 2.0000000000001. Different bytes, different hash.
    fn.body.children[0].children[0].children[1].children[0].value = 2.0000000000001
    assert fingerprint_module(make_module(fns=[fn])).module_hash != base


# ── Stability under cosmetic noise ─────────────────────────────────


def test_line_and_column_changes_do_not_affect_hash() -> None:
    base = fingerprint_module(make_module()).module_hash
    fn = make_gaussian_fn()
    fn.line = 42
    fn.col = 17
    fn.params[0].line = 99
    fn.params[0].col = 99
    # Recurse and bump every body node.
    def bump(n: ASTNode) -> None:
        n.line = 999
        n.col = 999
        for c in n.children:
            bump(c)
    bump(fn.body)
    assert fingerprint_module(make_module(fns=[fn])).module_hash == base


def test_absolute_path_does_not_affect_hash() -> None:
    base = fingerprint_module(make_module()).module_hash
    a = make_module()
    a.source_file = "/home/build/users/bob/checkout/gaussian.eml"
    assert fingerprint_module(a).module_hash == base


def test_profile_metadata_does_not_affect_tree_hash() -> None:
    """The profile is hashed *separately*, not inside ``tree_hash``."""
    base = fingerprint_module(make_module()).functions[0].tree_hash
    fn = make_gaussian_fn()
    fn.profile = {"chain_order": 1, "cost_class": "expensive"}
    assert fingerprint_function(fn).tree_hash == base


# ── Verify-contract isolation ──────────────────────────────────────


def test_verify_hash_is_none_when_no_contracts_declared() -> None:
    fn = make_gaussian_fn()
    fn.where_clauses = []
    assert fingerprint_function(fn).verify_hash is None


def test_verify_hash_changes_when_requires_changes() -> None:
    fn = make_gaussian_fn()
    base = fingerprint_function(fn).verify_hash    # has where-clause already
    fn.requires = [binop(">", var("sigma"), lit(0.0))]
    mutated = fingerprint_function(fn).verify_hash
    assert mutated is not None
    assert base != mutated


def test_verify_annotation_changes_verify_hash() -> None:
    fn = make_gaussian_fn()
    fn.annotations = []
    base = fingerprint_function(fn).verify_hash
    fn.annotations = [Annotation(kind="verify", args={"strict": True})]
    mutated = fingerprint_function(fn).verify_hash
    assert base != mutated


# ── Profile field whitelist ────────────────────────────────────────


def test_fpga_estimate_excluded_from_profile() -> None:
    fn = make_gaussian_fn()
    fn.profile = {
        "chain_order": 1,
        "fpga_estimate": {"mac_units": 99, "exp_units": 1},
        "fp16_drift_risk": "low",
    }
    fp = fingerprint_function(fn)
    assert "fpga_estimate" not in fp.profile
    assert fp.profile["chain_order"] == 1
    assert fp.profile["fp16_drift_risk"] == "low"


# ── Module hash composition ────────────────────────────────────────


def test_module_hash_changes_when_imports_change() -> None:
    a = make_module()
    b = make_module()
    b.imports = [EMLImport(path=["stdlib", "math"])]
    assert fingerprint_module(a).module_hash != fingerprint_module(b).module_hash


def test_module_hash_changes_when_constants_change() -> None:
    a = make_module()
    b = make_module()
    b.constants = [EMLConstant(name="PI", type_name="Real", value=lit(3.14))]
    assert fingerprint_module(a).module_hash != fingerprint_module(b).module_hash


# ── Schema-shape sanity ────────────────────────────────────────────


def test_to_json_roundtrips_through_python_json() -> None:
    fp = fingerprint_module(make_module())
    parsed = json.loads(fp.to_json(indent=None))
    assert parsed["spec"] == FINGERPRINT_SPEC
    assert parsed["module"]["source_file"] == "gaussian.eml"
    assert parsed["functions"][0]["name"] == "gaussian"
    assert parsed["functions"][0]["tree_hash"].startswith("sha256:")
    assert parsed["module_hash"].startswith("sha256:")


def test_machlib_defaults_to_null() -> None:
    """MachLib certificate hash is unpopulated until the resolver runs."""
    fp = fingerprint_module(make_module())
    assert fp.functions[0].machlib_cert_hash is None


def test_shape_class_id_is_null_when_no_profile() -> None:
    """Without a profile, the shape class can't be inferred."""
    fp = fingerprint_module(make_module())
    assert fp.functions[0].shape_class_id is None


def test_shape_class_id_populated_for_known_cost_class() -> None:
    """When the profiler has set ``cost_class`` to one of the 76
    canonical C-237 classes, the fingerprint should pin the ID."""
    fn = make_gaussian_fn()
    fn.profile = {"chain_order": 1, "cost_class": "p0-d3-w0-c0"}
    fp = fingerprint_function(fn)
    assert fp.shape_class_id == 0


def test_shape_class_id_null_for_out_of_corpus_class() -> None:
    fn = make_gaussian_fn()
    fn.profile = {"chain_order": 9, "cost_class": "p9-d9-w9-c9"}
    fp = fingerprint_function(fn)
    assert fp.shape_class_id is None


def test_sha256_hex_known_vector() -> None:
    # sha256("[]") = 11ed9ad7... (with our compact JSON encoding).
    # Anchor the hashing primitive against a literal so we'd notice
    # if someone changes the JSON encoder under us.
    h = sha256_hex([])
    assert h == "sha256:" + (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )


# ── Canonicalisation primitives ────────────────────────────────────


def test_canonicalize_node_handles_none() -> None:
    assert canonicalize_node(None) is None


def test_canonicalize_function_excludes_source_location() -> None:
    fn = make_gaussian_fn()
    fn.line = 17
    fn.col = 4
    fn.body.line = 99
    canon = canonicalize_function(fn)
    encoded = json.dumps(canon, sort_keys=True)
    assert "17" not in encoded or '"line"' not in encoded
    assert '"line"' not in encoded
    assert '"col"'  not in encoded
