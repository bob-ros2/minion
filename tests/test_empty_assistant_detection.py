#!/usr/bin/env python3
"""Tests for `_is_empty_assistant_message` and `_prune_empty_assistant_messages`.

These are the pure predicates that decide which assistant turns get pruned from
session files before persistence. They matter because an empty assistant turn
adds tokens to the model's context window without adding any signal — every
resume and every turn carries those dead messages forward.

Covered edge cases:
  1. Non-assistant roles are always "not empty".
  2. Assistant with tool_calls is always "not empty" (content may be None).
  3. Assistant with `None` content → empty.
  4. Assistant with whitespace-only string → empty.
  5. Assistant with non-empty string → not empty.
  6. Assistant with list content:
     a. All empty strings / empty-text dicts → empty.
     b. One non-empty string → not empty.
     c. One non-empty text dict → not empty.
     d. Empty list → empty.
  7. Non-string, non-list content → not empty (pass-through).
  8. `_prune_empty_assistant_messages` prunes in-place and returns counts.
"""

import minion as m  # noqa: E402


def _a(content=None, tool_calls=None):
    """Shortcut: build an assistant message."""
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def _u(content):
    return {"role": "user", "content": content}


# --- _is_empty_assistant_message: basic roles --------------------------------

def test_non_assistant_role_is_not_empty():
    assert m._is_empty_assistant_message({"role": "user", "content": ""}) is False
    assert m._is_empty_assistant_message({"role": "system", "content": ""}) is False
    assert m._is_empty_assistant_message({"role": "tool", "content": ""}) is False


def test_assistant_with_tool_calls_is_not_empty():
    # Even if content is None, tool_calls means the turn is not empty.
    assert m._is_empty_assistant_message(_a(content=None, tool_calls=[{}])) is False
    assert m._is_empty_assistant_message(_a(content="", tool_calls=[{}])) is False


# --- _is_empty_assistant_message: string content -----------------------------

def test_none_content_is_empty():
    assert m._is_empty_assistant_message(_a(content=None)) is True
    # missing "content" key behaves the same
    msg = _a()
    del msg["content"]
    assert m._is_empty_assistant_message(msg) is True


def test_whitespace_only_string_is_empty():
    assert m._is_empty_assistant_message(_a(content="")) is True
    assert m._is_empty_assistant_message(_a(content="   ")) is True
    assert m._is_empty_assistant_message(_a(content="\n\t\n")) is True


def test_nonempty_string_is_not_empty():
    assert m._is_empty_assistant_message(_a(content="hello")) is False
    assert m._is_empty_assistant_message(_a(content=" hi ")) is False


# --- _is_empty_assistant_message: list content --------------------------------

def test_empty_list_is_empty():
    assert m._is_empty_assistant_message(_a(content=[])) is True


def test_all_empty_strings_in_list_is_empty():
    assert m._is_empty_assistant_message(_a(content=["", "  ", ""])) is True
    assert m._is_empty_assistant_message(_a(content=["\n", "  \n"])) is True


def test_one_nonempty_string_in_list_is_not_empty():
    assert m._is_empty_assistant_message(_a(content=["", "hello", ""])) is False
    assert m._is_empty_assistant_message(_a(content=["  ", " real ", "  "])) is False


def test_empty_text_dicts_are_empty():
    assert m._is_empty_assistant_message(
        _a(content=[{"type": "text", "text": ""}, {"type": "text", "text": "  "}])
    ) is True


def test_nonempty_text_dict_is_not_empty():
    assert m._is_empty_assistant_message(
        _a(content=[{"type": "text", "text": ""}, {"type": "text", "text": "hello"}])
    ) is False
    assert m._is_empty_assistant_message(
        _a(content=[{"type": "text", "text": "hello"}])
    ) is False


def test_mixed_list_with_nonempty_string():
    assert m._is_empty_assistant_message(
        _a(content=["", {"type": "text", "text": ""}, " real thing", {}])
    ) is False


def test_mixed_list_all_empty():
    assert m._is_empty_assistant_message(
        _a(content=["", {"type": "text", "text": ""}, {"text": "  "}])
    ) is True


# --- _is_empty_assistant_message: other content types ------------------------

def test_non_string_non_list_content_is_not_empty():
    # Edge case: content is some unexpected type (int, bool, …).
    # The function falls through to `return False` — "not empty".
    assert m._is_empty_assistant_message(_a(content=42)) is False
    assert m._is_empty_assistant_message(_a(content=False)) is False


# --- _prune_empty_assistant_messages -----------------------------------------

def test_prune_removes_empty_assistant_messages():
    msgs = [
        _u("hi"),
        _a(content=None),
        _a(content="   "),
        _a(content="hello"),
        _u("bye"),
    ]
    removed = m._prune_empty_assistant_messages(msgs)
    assert removed == 2
    assert msgs == [
        _u("hi"),
        _a(content="hello"),
        _u("bye"),
    ]


def test_prune_keeps_assistant_with_tool_calls():
    msgs = [
        _a(content=None, tool_calls=[{"id": "t1", "function": {}}]),
        _u("hi"),
    ]
    removed = m._prune_empty_assistant_messages(msgs)
    assert removed == 0
    assert len(msgs) == 2


def test_prune_non_list_returns_zero():
    assert m._prune_empty_assistant_messages("not a list") == 0
    assert m._prune_empty_assistant_messages(None) == 0
    assert m._prune_empty_assistant_messages({}) == 0


def test_prune_does_not_modify_if_nothing_removed():
    msgs = [_u("hi"), _a(content="hello")]
    orig_ids = [id(m) for m in msgs]
    removed = m._prune_empty_assistant_messages(msgs)
    assert removed == 0
    assert [id(m) for m in msgs] == orig_ids  # list identity preserved


if __name__ == "__main__":
    import pytest

    import sys
    sys.exit(pytest.main([__file__, "-v"]))
