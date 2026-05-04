"""LSP hover smoke tests.

Cover the three branches of `_hover_markdown`:
  - builtin transcendental (e.g. `exp`)
  - locally-defined function (profile must be filled in by the
    on-demand profiler so the card carries real numbers, not `?`)
  - miss (unknown word -> None)

Plus the cache invariant: re-rendering the same (uri, source) must
not re-run the profiler.
"""

from __future__ import annotations

import pytest

from tools.ide.lsp import server as lsp_server


HELLO_SRC = """\
module test_hover;

fn double(x: Real) -> Real
    where chain_order <= 0
{
    x + x
}
"""


@pytest.fixture(autouse=True)
def _clean_doc_cache():
    """Each test gets a clean module-level cache."""
    lsp_server._DOC_CACHE.clear()
    yield
    lsp_server._DOC_CACHE.clear()


def test_hover_builtin_returns_chain_delta_card():
    md = lsp_server._hover_markdown(HELLO_SRC, "exp", uri="file:///t.eml")
    assert md is not None
    assert "builtin transcendental" in md
    assert "chain-order delta" in md
    # exp's published delta is +1 -- the card must reflect that.
    assert "+1" in md


def test_hover_user_function_carries_profile_data():
    md = lsp_server._hover_markdown(HELLO_SRC, "double", uri="file:///t.eml")
    assert md is not None
    # The on-demand profiler must populate the card -- we should
    # NEVER see a `?` for chain order or cost class on a function
    # that parses cleanly.
    assert "chain order **?**" not in md
    assert "cost class `?`" not in md
    # `double(x) = x + x` is plain polynomial arithmetic -> chain 0.
    assert "chain order **0**" in md


def test_hover_unknown_word_returns_none():
    md = lsp_server._hover_markdown(HELLO_SRC, "no_such_thing",
                                    uri="file:///t.eml")
    assert md is None


def test_hover_empty_word_returns_none():
    md = lsp_server._hover_markdown(HELLO_SRC, "", uri="file:///t.eml")
    assert md is None


def test_hover_caches_parsed_module_across_calls(monkeypatch):
    """Hover, completion, and definition all reparse the open
    document on every request. With the cache in place, two hover
    calls with the same source must produce exactly one parse and
    one profile pass."""
    parse_calls = {"n": 0}
    real_parse = lsp_server.parse_source

    def counting_parse(*args, **kwargs):
        parse_calls["n"] += 1
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(lsp_server, "parse_source", counting_parse)

    profile_calls = {"n": 0}
    real_profile = lsp_server._profiler().profile_module

    def counting_profile(mod):
        profile_calls["n"] += 1
        return real_profile(mod)

    monkeypatch.setattr(lsp_server._profiler(),
                        "profile_module", counting_profile)

    lsp_server._hover_markdown(HELLO_SRC, "double", uri="file:///c.eml")
    lsp_server._hover_markdown(HELLO_SRC, "double", uri="file:///c.eml")

    assert parse_calls["n"] == 1
    assert profile_calls["n"] == 1


def test_hover_reparse_when_source_changes():
    """Bumping the source content evicts the old parse."""
    src_v1 = HELLO_SRC
    src_v2 = HELLO_SRC.replace("double", "twice")

    md1 = lsp_server._hover_markdown(src_v1, "double", uri="file:///e.eml")
    md2 = lsp_server._hover_markdown(src_v2, "twice",  uri="file:///e.eml")
    md3 = lsp_server._hover_markdown(src_v2, "double", uri="file:///e.eml")

    assert md1 is not None  # `double` exists in v1
    assert md2 is not None  # `twice` exists in v2
    assert md3 is None      # `double` no longer exists in v2
