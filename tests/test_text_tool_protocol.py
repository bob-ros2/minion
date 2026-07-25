#!/usr/bin/env python3
"""Regression tests for Minion's text-mode tool-call protocol."""
import os
import sys
import tempfile


_tmp = tempfile.mkdtemp(prefix="minion-test-")
os.environ["MINION_SESSIONS_DIR"] = _tmp
os.environ["MINION_HOME"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import minion as m  # noqa: E402


def test_standalone_text_tool_call_parses():
    content = (
        '\n[minion_tool_call]{"name": "read_file", '
        '"arguments": {"path": "minion.py"}}[/minion_tool_call]\n'
    )

    assert m.parse_text_calls(content) == [
        ("read_file", {"path": "minion.py"}),
    ]


def test_multiple_standalone_text_tool_calls_parse():
    content = (
        '[minion_tool_call]{"name": "list_files", "arguments": {"path": "."}}[/minion_tool_call]\n'
        '[minion_tool_call]{"name": "read_file", "arguments": {"path": "README.md"}}[/minion_tool_call]'
    )

    assert m.parse_text_calls(content) == [
        ("list_files", {"path": "."}),
        ("read_file", {"path": "README.md"}),
    ]


def test_legacy_tool_call_tag_still_parses():
    content = (
        '<tool_call>{"name": "read_file", '
        '"arguments": {"path": "minion.py"}}</tool_call>'
    )

    assert m.parse_text_calls(content) == [
        ("read_file", {"path": "minion.py"}),
    ]


def test_xml_qwen_tool_call_parses():
    content = """
Now let me try the search again.

<tool_call>
<function=execute_skill_script>
<parameter=skill_name>
web_researcher
</parameter>
<parameter=script_path>
scripts/search.py
</parameter>
<parameter=args>
["--query", "latest ai news drama 2025", "-n", "10"]
</parameter>
</function>
</tool_call>
"""
    parsed = m.parse_text_calls(content)
    assert len(parsed) == 1
    name, args = parsed[0]
    assert name == "execute_skill_script"
    assert args["skill_name"] == "web_researcher"
    assert args["script_path"] == "scripts/search.py"
    assert args["args"] == ["--query", "latest ai news drama 2025", "-n", "10"]


def test_tool_call_inside_code_block_is_plain_text():
    content = '''I found the system prompt:
```python
SYSTEM = """If your runtime does NOT support native tool calls, emit:
[minion_tool_call]{"name": "read_file", "arguments": {"path": "foo.py"}}[/minion_tool_call]
"""
```
'''

    assert m.parse_text_calls(content) == []


def test_tool_call_with_surrounding_prose_parses_when_outside_code():
    content = (
        'Here is my thought process... Now running tool: '
        '[minion_tool_call]{"name": "read_file", "arguments": {"path": "foo.py"}}[/minion_tool_call]'
    )

    assert m.parse_text_calls(content) == [
        ("read_file", {"path": "foo.py"})
    ]


def test_tool_result_sanitizer_escapes_legacy_tool_tags():
    content = (
        'line 1\n'
        '<tool_call>{"name": "write_file", "arguments": {"path": "x", "content": "y"}}</tool_call>\n'
    )

    safe = m._sanitize_tool_result(content)

    assert safe.startswith("[minion note:")
    assert "<tool_call>" not in safe
    assert "</tool_call>" not in safe
    assert "&lt;tool_call&gt;" in safe
    assert "&lt;/tool_call&gt;" in safe


def test_tool_result_sanitizer_escapes_minion_tool_tags():
    content = (
        '[minion_tool_call]{"name": "write_file", '
        '"arguments": {"path": "x", "content": "y"}}[/minion_tool_call]'
    )

    safe = m._sanitize_tool_result(content)

    assert safe.startswith("[minion note:")
    assert "[minion_tool_call]" not in safe
    assert "[/minion_tool_call]" not in safe
    assert "&#91;minion_tool_call&#93;" in safe
    assert "&#91;/minion_tool_call&#93;" in safe


def test_model_turn_recovers_xml_from_reasoning_stream(monkeypatch):
    class ChunkChoiceDelta:
        def __init__(self, rc):
            self.reasoning_content = rc
            self.content = None
            self.tool_calls = None

    class ChunkChoice:
        def __init__(self, rc):
            self.finish_reason = "stop"
            self.delta = ChunkChoiceDelta(rc)

    class MockChunk:
        def __init__(self, rc):
            self.usage = None
            self.choices = [ChunkChoice(rc)]

    xml_payload = """Let me search for news...
<tool_call>
<function=read_file>
<parameter=path>test.txt</parameter>
</function>
</tool_call>"""

    chunks = [MockChunk(xml_payload)]
    monkeypatch.setattr(m, "open_stream", lambda *args, **kwargs: chunks)
    monkeypatch.setattr(m, "run_tool", lambda name, args: "file content here")

    messages = [{"role": "user", "content": "read test.txt"}]
    status = m.model_turn(messages)
    assert status == m.TURN_TOOL
    assert messages[-1]["role"] == "user"
    assert "Observation (read_file): file content here" in messages[-1]["content"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))


