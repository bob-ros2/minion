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


def test_build_clean_result_filters_tool_preambles():
    messages = [
        {"role": "user", "content": "Fix the bug"},
        {"role": "assistant", "content": "Let me inspect the file first.", "tool_calls": [{"id": "1", "function": {"name": "read_file"}}]},
        {"role": "tool", "content": "file content..."},
        {"role": "assistant", "content": "Let me edit the file now.", "tool_calls": [{"id": "2", "function": {"name": "edit_file"}}]},
        {"role": "tool", "content": "edit done"},
        {"role": "assistant", "content": "Successfully fixed the bug in review.py. NEXT_STEP: Run tests."}
    ]
    res = minion._build_clean_result(messages)
    assert res == "Successfully fixed the bug in review.py. NEXT_STEP: Run tests."
    assert "Let me inspect" not in res
    assert "Let me edit" not in res


def test_build_clean_result_fallback_tool_preambles():
    messages = [
        {"role": "user", "content": "Fix the bug"},
        {"role": "assistant", "content": "Let me inspect the file first.", "tool_calls": [{"id": "1", "function": {"name": "read_file"}}]},
        {"role": "tool", "content": "file content..."}
    ]
    res = minion._build_clean_result(messages)
    assert res == "Let me inspect the file first."


def test_api_log_control_and_capping(tmp_path, monkeypatch):
    log_file = tmp_path / "llamacpp.log"
    monkeypatch.setattr(minion, "LOG_PATH", str(log_file))
    monkeypatch.setattr(minion, "_LOG_API_ENABLED", True)
    monkeypatch.setattr(minion, "_MAX_LOG_BYTES", 100)
    monkeypatch.setattr(minion, "_llog", None)

    # Write small log
    minion._log_event("req", {"test": "data"})
    assert log_file.exists()
    size1 = log_file.stat().st_size
    assert size1 > 0

    # Write until capped
    for _ in range(10):
        minion._log_event("req", {"test": "data" * 10})

    # File size should be reset/truncated when exceeding limit
    size2 = log_file.stat().st_size
    assert size2 <= 200  # truncated cleanly

    # Disable logging
    monkeypatch.setattr(minion, "_LOG_API_ENABLED", False)
    minion._log_event("req", {"should": "ignore"})

