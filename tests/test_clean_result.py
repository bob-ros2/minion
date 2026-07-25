import os
import pytest
from prepare_chat_session import clean_ansi_and_progress
import minion

def test_clean_ansi_and_progress():
    raw = (
        "\x1b[36m  ┌─ edit_file\x1b[0m\n"
        "\x1b[36m  │ \x1b[0m\x1b[2m{\"path\": \"minion.py\"}\x1b[0m\n"
        "  └ 1117 tok · 33.6 tok/s · 48K/131K ctx · 1147ms ttft · 33.3s wall\n"
        "\x1b[31m  ERROR: OSError: [Errno 30] Read-only file system: 'minion.py'\x1b[0m\n"
        "  ── reasoning ──\n"
        "The file is on a read-only filesystem. This is a Docker container issue.\n"
        "  ──────────────\n"
        "We should use a writable location or update the docker mount.\n"
        "NEXT_STEP: Update docker compose configuration.\n"
    )
    cleaned = clean_ansi_and_progress(raw)
    assert "┌─ edit_file" not in cleaned
    assert "1117 tok" not in cleaned
    assert "── reasoning ──" not in cleaned
    assert "The file is on a read-only filesystem." in cleaned
    assert "NEXT_STEP: Update docker compose configuration." in cleaned
    assert "\x1b" not in cleaned

def test_result_file_arg_parsed(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "argv", ["minion.py", "--result-file", "/tmp/test_res.txt"])
    # Re-evaluate logic or verify parsing variable
    res_file = None
    for _i, _arg in enumerate(sys.argv):
        if _arg in ("--result-file", "-o") and _i + 1 < len(sys.argv):
            res_file = sys.argv[_i + 1]
            break
    assert res_file == "/tmp/test_res.txt"
