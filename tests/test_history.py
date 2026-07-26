import os
import pytest
import minion

def test_summarize_prompt():
    # 1. Extract Session Source line if present
    prompt_with_source = (
        "# Self-Evolution Task\n\n"
        "## Your last response (if any):\n"
        "### Session Source: 20260725-231838-7b8067.json\n\n"
        "Some prior content..."
    )
    summary1 = minion._summarize_prompt(prompt_with_source)
    assert summary1 == "Session Source: 20260725-231838-7b8067.json"

    # 2. General task instruction summarization
    prompt_general = (
        "# Task\n"
        "Fix the authentication bug in login_handler.py.\n"
        "Ensure all tests pass before submitting."
    )
    summary2 = minion._summarize_prompt(prompt_general)
    assert "Fix the authentication bug in login_handler.py." in summary2

    # 3. Empty prompt handling
    assert minion._summarize_prompt("") == "(empty prompt)"


def test_append_history_entry(tmp_path):
    hist_file = tmp_path / "evolve" / "history.txt"
    sid = "20260726-021744-49a87e"
    prompt = "### Session Source: 20260725-231838-7b8067.json"
    result = "Refactored error log handling.\nNEXT_STEP: Add unit tests."

    minion._append_history_entry(str(hist_file), sid, prompt, result)

    assert hist_file.exists()
    content = hist_file.read_text(encoding="utf-8")
    assert f"Session: {sid} (49a87e)" in content
    assert "Prompt: Session Source: 20260725-231838-7b8067.json" in content
    assert "Refactored error log handling." in content
    assert "NEXT_STEP: Add unit tests." in content

    # Append second entry
    minion._append_history_entry(str(hist_file), "20260726-030000-112233", "New task", "Done step 2.")
    content2 = hist_file.read_text(encoding="utf-8")
    assert content2.count("--- [") == 2
    assert "Done step 2." in content2


def test_history_file_arg_and_default(tmp_path, monkeypatch):
    res_file = tmp_path / "evolve" / "result.txt"
    monkeypatch.setattr(minion, "_RESULT_FILE", str(res_file))
    monkeypatch.setattr(minion, "_HISTORY_FILE", str(tmp_path / "evolve" / "history.txt"))

    assert minion._HISTORY_FILE == str(tmp_path / "evolve" / "history.txt")
