"""Tests for `lang.parser.lexer`."""

from __future__ import annotations

import pytest

from lang.parser.lexer import LexError, tokenize


def _tok_kinds(src: str) -> list[str]:
    return [t.kind for t in tokenize(src)]


def test_empty_source_emits_only_eof():
    assert _tok_kinds("") == ["EOF"]


def test_whitespace_only_emits_only_eof():
    assert _tok_kinds("   \n\t  \r\n  ") == ["EOF"]


def test_line_comment_is_skipped():
    toks = _tok_kinds("// this is a comment\n42")
    assert toks == ["INT", "EOF"]


def test_block_comment_is_skipped():
    toks = _tok_kinds("/* skip */ 42 /* and this */")
    assert toks == ["INT", "EOF"]


def test_unterminated_block_comment_raises():
    with pytest.raises(LexError):
        tokenize("/* never closed")


def test_keywords_recognized():
    toks = tokenize("fn const let mut while where")
    assert all(t.kind == "KEYWORD" for t in toks[:6])
    assert [t.value for t in toks[:6]] == [
        "fn", "const", "let", "mut", "while", "where",
    ]


def test_identifiers_with_underscores_and_digits():
    toks = tokenize("Kp last_error _hidden x1 x_2_y")
    assert all(t.kind == "IDENT" for t in toks[:5])


def test_int_and_float_distinction():
    toks = tokenize("42 3.14 1e10 1.5e-3 0.001")
    kinds = [t.kind for t in toks if t.kind != "EOF"]
    assert kinds == ["INT", "FLOAT", "FLOAT", "FLOAT", "FLOAT"]


def test_string_literal():
    toks = tokenize('"hello world"')
    assert toks[0].kind == "STRING"
    assert toks[0].value == "hello world"


def test_multi_char_operators():
    toks = tokenize("-> <= >= == != && ||")
    kinds = [t.kind for t in toks if t.kind != "EOF"]
    assert kinds == ["ARROW", "LE", "GE", "EQ", "NE", "AND", "OR"]


def test_single_char_operators():
    # Spaces separate the comparison chars so longest-match doesn't
    # collapse `>=` from `>` `=` neighbors.
    toks = tokenize("+ - * / < > = ( ) ; { } [ ] , . ! @ :")
    kinds = [t.kind for t in toks if t.kind != "EOF"]
    assert kinds == [
        "PLUS", "MINUS", "STAR", "SLASH",
        "LT", "GT", "ASSIGN",
        "LPAREN", "RPAREN", "SEMI",
        "LBRACE", "RBRACE",
        "LBRACK", "RBRACK",
        "COMMA", "DOT", "BANG", "AT", "COLON",
    ]


def test_longest_match_for_compound_operators():
    """Lexer should prefer `<=` over `<` `=` when both match."""
    toks = tokenize("<= >= == != -> && ||")
    kinds = [t.kind for t in toks if t.kind != "EOF"]
    assert kinds == ["LE", "GE", "EQ", "NE", "ARROW", "AND", "OR"]


def test_source_location_is_correct():
    toks = tokenize("fn\n  answer")
    fn_tok, name_tok = toks[0], toks[1]
    assert fn_tok.line == 1 and fn_tok.col == 1
    assert name_tok.line == 2 and name_tok.col == 3


def test_unknown_character_raises_with_location():
    # Phase A added '^' as CARET for unit exponentiation (e.g. s^2).
    # Use '#' which remains an unrecognized character.
    with pytest.raises(LexError) as exc:
        tokenize("fn # bad")
    assert "line 1:4" in str(exc.value)


def test_caret_is_lexed_as_caret_token():
    """Phase A: '^' is now CARET, used in unit expressions like s^2."""
    toks = tokenize("s^2")
    kinds = [t.kind for t in toks if t.kind != "EOF"]
    assert kinds == ["IDENT", "CARET", "INT"]
