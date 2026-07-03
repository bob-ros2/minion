#!/usr/bin/env python3
"""Tests for auto context-compression (MINION_AUTOCOMPRESS_PERCENT + /autocompress).

Covers:
  - compress(messages, auto=True) keeps ~1/3 of the body verbatim (more than
    the manual COMPRESS_KEEP=2), so in-progress work survives the fold.
  - _maybe_autocompress() fires only past the threshold, is a no-op below it,
    and is a no-op when the context window is unknown.
  - /autocompress bare shows the current %, /autocompress <n> sets it,
    /autocompress off disables, /autocompress on re-enables.
  - the REPL loop calls _maybe_autocompress after a settled turn and triggers
    a compress when over threshold.

Offline: compress() and model_turn() are stubbed so no network is needed.
"""
import builtins
import io
import os
import sys
import tempfile
import importlib

_tmp = tempfile.mkdtemp(prefix="minion-autocomp-")
os.environ["MINION_SESSIONS_DIR"] = _tmp
os.environ["MINION_HOME"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import minion as m  # noqa: E402


class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]
    def model_dump(self):
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}


class _FakeCompletions:
    def create(self, **kwargs):
        return _FakeResp("fake summary of the conversation")


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


_compress_calls = []


# A stub compress used by tests. It records (keep, auto) and mimics the
# keep-count logic so _maybe_autocompress's return value is realistic.
def _stub_compress(msgs, keep=m.COMPRESS_KEEP, auto=False):
    _compress_calls.append((keep, auto))
    sys_msg = msgs[0] if msgs and msgs[0].get("role") == "system" else None
    body = msgs[1:] if sys_msg else msgs
    kept = max(keep, len(body) // 3) if auto else keep
    if len(body) <= kept:
        return None
    summarized = len(body) - kept
    msgs[:] = ([sys_msg] if sys_msg else []) + [
        {"role": "user", "content": "[Compressed context — fake summary]"}] + body[-kept:]
    return (kept, summarized, 42)


class _FakeSource:
    def __init__(self, ctx_window):
        self._context_window = ctx_window
        self.name = "fake"


def run_repl_commands(commands):
    """Feed a list of commands to main() and return captured stdout."""
    captured = io.StringIO()
    real_print = builtins.print

    def fake_print(*a, **kw):
        captured.write(" ".join(str(x) for x in a) + (kw.get("end", "\n")))

    builtins.print = fake_print
    prompts = iter(list(commands) + ["/quit"])
    m.read_multiline = lambda history=None: next(prompts)
    m.open_stream = lambda *a, **k: iter([])  # no network
    m.model_turn = lambda *a, **k: m.TURN_DONE
    m.compress = _stub_compress  # stub so /compress never hits network
    m.YOLO = True
    try:
        m.main()
    finally:
        builtins.print = real_print
    return captured.getvalue()


def test_compress_auto_keeps_one_third():
    _real_client = m.client
    _real_model = m.MODEL
    m.client = _FakeClient()
    m.MODEL = "test-model"

    try:
        # 30 body turns (60 messages) + system = 61. auto keep = 60 // 3 = 20.
        result = m.compress(list([{"role": "system", "content": m.SYSTEM}] +
                                 [{"role": "user" if j % 2 == 0 else "assistant",
                                    "content": f"turn {j // 2}"} for j in range(60)]),
                            auto=True)
        kept_n, summarized_n, _ = result
        assert kept_n == 20, f"auto should keep 20 (1/3 of 60), got {kept_n}"
        assert summarized_n == 40, f"auto should summarize 40, got {summarized_n}"

        # Same messages with auto=False (manual) → keeps only COMPRESS_KEEP (2)
        msgs_manual = [{"role": "system", "content": m.SYSTEM}] + \
            [{"role": "user" if j % 2 == 0 else "assistant", "content": f"turn {j // 2}"}
             for j in range(60)]
        result = m.compress(msgs_manual, auto=False)
        kept_n, summarized_n, _ = result
        assert kept_n == m.COMPRESS_KEEP, f"manual should keep COMPRESS_KEEP ({m.COMPRESS_KEEP}), got {kept_n}"

        # Small conversation: auto keep (body//3) should not exceed body size → None
        msgs_small = [{"role": "system", "content": m.SYSTEM}] + \
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        result = m.compress(msgs_small, auto=True)
        assert result is None, f"too-small conversation should return None, got {result}"
    finally:
        m.client = _real_client
        m.MODEL = _real_model


def test_maybe_autocompress_guards():
    _real_compress = m.compress
    _real_active = m.ACTIVE
    _real_autocompress_percent = m.AUTOCOMPRESS_PERCENT

    m.ACTIVE = _FakeSource(10000)
    m.AUTOCOMPRESS_PERCENT = 85

    test_msgs = [{"role": "system", "content": m.SYSTEM}]
    for i in range(10):
        test_msgs.append({"role": "user", "content": f"turn {i}"})
        test_msgs.append({"role": "assistant", "content": f"reply {i}"})

    try:
        # (a) below threshold → no compress
        m.compress = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not compress"))
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=5000)  # 50% < 85%
        assert fired is False, "should not fire below threshold"

        # (b) at/above threshold → compress fires
        _compress_calls.clear()
        m.compress = _stub_compress
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=8500)  # 85% ≥ 85%
        assert fired is True, "should fire at threshold"
        assert _compress_calls and _compress_calls[-1][1] is True, "should call compress(auto=True)"
        _compress_calls.clear()

        # (c) disabled (0%) → no compress even at 100%
        m.AUTOCOMPRESS_PERCENT = 0
        m.compress = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not compress when off"))
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=10000)
        assert fired is False, "should not fire when disabled"
        m.AUTOCOMPRESS_PERCENT = 85  # restore

        # (d) unknown window (None) → no compress
        m.ACTIVE = _FakeSource(None)
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=9999)
        assert fired is False, "should not fire with unknown window"

        # (e) window = 0 → no compress
        m.ACTIVE = _FakeSource(0)
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=9999)
        assert fired is False, "should not fire with zero window"

        # (f) ACTIVE = None → no compress
        m.ACTIVE = None
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=9999)
        assert fired is False, "should not fire with no active source"

        # (g) prompt_tokens = 0 / negative → no compress
        m.ACTIVE = _FakeSource(10000)
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=0)
        assert fired is False, "should not fire with zero prompt tokens"
        fired = m._maybe_autocompress(test_msgs, prompt_tokens=-1)
        assert fired is False, "should not fire with negative prompt tokens"
    finally:
        m.compress = _real_compress
        m.ACTIVE = _real_active
        m.AUTOCOMPRESS_PERCENT = _real_autocompress_percent


def test_autocompress_command_parsing():
    _real_active = m.ACTIVE
    _real_autocompress_percent = m.AUTOCOMPRESS_PERCENT

    m.ACTIVE = _FakeSource(10000)
    m.AUTOCOMPRESS_PERCENT = 85

    try:
        # bare /autocompress → shows current %
        out = run_repl_commands(["/autocompress"])
        assert "auto-compress: 85%" in out, f"bare /autocompress should show 85%: {out!r}"

        # /autocompress 70 → sets to 70
        out = run_repl_commands(["/autocompress 70"])
        assert "auto-compress: 70%" in out, f"/autocompress 70 should set 70%: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == 70

        # /autocompress off → disables
        out = run_repl_commands(["/autocompress off"])
        assert "auto-compress: off" in out, f"/autocompress off should disable: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == 0

        # bare /autocompress when off → shows "off"
        out = run_repl_commands(["/autocompress"])
        assert "auto-compress: off" in out, f"bare when off should show off: {out!r}"

        # /autocompress on → re-enables at the configured default (85 here)
        out = run_repl_commands(["/autocompress on"])
        assert f"auto-compress: {m.AUTOCOMPRESS_DEFAULT}%" in out, \
            f"/autocompress on should restore the configured default: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == m.AUTOCOMPRESS_DEFAULT

        # /autocompress 0 → disables (alias for off)
        out = run_repl_commands(["/autocompress 0"])
        assert "auto-compress: off" in out, f"/autocompress 0 should disable: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == 0

        # /autocompress 999 → out of range
        m.AUTOCOMPRESS_PERCENT = 50
        out = run_repl_commands(["/autocompress 999"])
        assert "out of range" in out, f"999 should be out of range: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == 50, "should be unchanged after invalid input"

        # /autocompress abc → usage message
        out = run_repl_commands(["/autocompress abc"])
        assert "usage" in out.lower(), f"abc should show usage: {out!r}"
    finally:
        m.ACTIVE = _real_active
        m.AUTOCOMPRESS_PERCENT = _real_autocompress_percent


def test_autocompress_env_var():
    global m
    saved_env = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("MINION_"):
            del os.environ[k]
    os.environ["MINION_ENV_FILE"] = "/dev/null"
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_AUTOCOMPRESS_PERCENT"] = "60"
    sys.argv = ["minion.py"]
    importlib.reload(m)

    try:
        assert m.AUTOCOMPRESS_PERCENT == 60, f"env 60 → {m.AUTOCOMPRESS_PERCENT}"

        # /autocompress on restores the *configured* default (60), not a hardcoded 85.
        assert m.AUTOCOMPRESS_DEFAULT == 60, \
            f"AUTOCOMPRESS_DEFAULT should track the env default, got {m.AUTOCOMPRESS_DEFAULT}"
        out = run_repl_commands(["/autocompress off", "/autocompress on"])
        assert "auto-compress: 60%" in out, \
            f"/autocompress on should restore the configured 60%, not 85: {out!r}"
        assert m.AUTOCOMPRESS_PERCENT == 60, \
            f"on should restore configured 60, got {m.AUTOCOMPRESS_PERCENT}"

        # clamp upper bound
        os.environ["MINION_AUTOCOMPRESS_PERCENT"] = "150"
        importlib.reload(m)
        assert m.AUTOCOMPRESS_PERCENT == 100, f"env 150 should clamp to 100, got {m.AUTOCOMPRESS_PERCENT}"

        # clamp lower bound
        os.environ["MINION_AUTOCOMPRESS_PERCENT"] = "-5"
        importlib.reload(m)
        assert m.AUTOCOMPRESS_PERCENT == 0, f"env -5 should clamp to 0, got {m.AUTOCOMPRESS_PERCENT}"
    finally:
        # restore env
        for k in list(os.environ):
            if k.startswith("MINION_"):
                del os.environ[k]
        os.environ.update({k: v for k, v in saved_env.items() if k.startswith("MINION_") or k == "MINION_ENV_FILE"})
        importlib.reload(m)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
