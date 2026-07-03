#!/usr/bin/env python3
"""Tests for the footer token abbreviators `_abbr` and `_precise_abbr`.

`_precise_abbr` keeps two decimals across K/M/B; the B branch used to floor to
an integer ("1B"), so the two-decimal case there is pinned below.

Uses shared fixtures from ``conftest.py`` for temp-dir setup.
"""

import minion as m  # noqa: E402


def test_abbr_ranges():
    assert m._abbr(832) == "832"
    assert m._abbr(1500) == "1.5K"
    assert m._abbr(78825) == "78K"
    assert m._abbr(1234567) == "1.2M"


def test_precise_abbr_keeps_two_decimals():
    assert m._precise_abbr(832) == "832"
    assert m._precise_abbr(25152) == "25.15K"
    assert m._precise_abbr(1234567) == "1.23M"


def test_precise_abbr_billions_two_decimals(tmp_minion):
    """The B branch used to floor to an integer ("1B").

    The ``tmp_minion`` fixture ensures a clean temp dir / env state, even
    though ``_precise_abbr`` itself is a pure function and doesn't touch the
    filesystem.
    """
    assert m._precise_abbr(1_500_000_000) == "1.50B"
    assert m._precise_abbr(2_000_000_000) == "2.00B"


if __name__ == "__main__":
    import pytest

    import sys
    sys.exit(pytest.main([__file__, "-v"]))
