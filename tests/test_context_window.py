#!/usr/bin/env python3
"""Tests for Source.resolve_context_window() — the max-context probe that
backs the footer's `ctx N/<max>` suffix and the /source listing's `· N ctx`.

No live server: the three probe paths (GET /v1/models, GET /props, and the
over-max_tokens chat error) are monkeypatched so the tests are offline and
deterministic. Covers:
  - llama.cpp: n_ctx found in data[0].meta (via __pydantic_extra__)
  - llama.cpp fallback: default_generation_settings.n_ctx from /props
  - Together: models list empty + /props 404 → over-max_tokens 400 names the limit
  - caching: second call doesn't re-probe (force=True bypasses the cache)
  - cache invalidation: switch_source() clears the cached window
  - total miss: all probes fail → None, footer omits the suffix gracefully
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Scrub env so _discover_sources builds a clean single 'local' source.
for k in list(os.environ):
    if k.startswith("MINION_"):
        del os.environ[k]
os.environ.pop("TOGETHER_API_KEY", None)
os.environ["MINION_ENV_FILE"] = "/dev/null"
os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
sys.argv = ["minion.py"]
import minion as m  # noqa: E402


class _FakeModel:
    """Stand-in for openai.types.model.Model. The real one keeps unknown fields
    in __pydantic_extra__ (config extra='allow'); resolve_context_window reads
    meta.n_ctx / context_length from there."""
    def __init__(self, mid, extra=None):
        self.id = mid
        self.created = 0
        self.object = "model"
        self.owned_by = "test"
        self.__pydantic_extra__ = extra or {}


class _FakeModelsPage:
    def __init__(self, data):
        self.data = data


class _FakeChatCompletions:
    """Raises a BadRequestError-shaped exception carrying the context-length
    message, mimicking Together's over-max_tokens 400 response."""
    def __init__(self, msg=None):
        self._msg = msg

    def create(self, **kwargs):
        if self._msg is None:
            # Simulate a provider that accepts the request and would generate
            # — the probe should NOT parse anything from a successful call.
            return object()
        e = RuntimeError(self._msg)
        e.body = json.loads(self._msg.split(" - ", 1)[1]) if " - " in self._msg else None
        raise e


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeModels:
    def __init__(self, page):
        self._page = page

    def list(self, **kwargs):
        return self._page


class _FakeClient:
    def __init__(self, models_page=None, chat=None):
        self.models = _FakeModels(models_page)
        self.chat = chat or _FakeChat(_FakeChatCompletions())


def _make_source(models_page=None, chat=None):
    src = m.Source("test", "http://localhost:8080/v1", "sk-noop", "test-model")
    src.client = _FakeClient(models_page, chat)
    return src


@pytest.mark.sources
@pytest.mark.network
def test_llama_cpp_n_ctx_from_models_meta():
    page = _FakeModelsPage([_FakeModel("test-model", {"meta": {"n_ctx": 131072}})])
    src = _make_source(models_page=page, chat=_FakeChat(_FakeChatCompletions()))
    n = src.resolve_context_window()
    assert n == 131072, f"expected 131072 from meta.n_ctx, got {n}"


@pytest.mark.sources
@pytest.mark.network
def test_props_fallback():
    props = {"default_generation_settings": {"n_ctx": 65536},
             "model_alias": "test-model"}
    orig_urlopen = urllib.request.urlopen
    calls = []

    class _FakeResp:
        def __init__(self, body):
            self._body = body.encode() if isinstance(body, str) else body
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake_urlopen(url, timeout=None):
        calls.append(str(url))
        if "/props" in str(url):
            return _FakeResp(json.dumps(props))
        raise urllib.error.URLError("nope")

    urllib.request.urlopen = _fake_urlopen
    try:
        src = _make_source(models_page=_FakeModelsPage([]),
                           chat=_FakeChat(_FakeChatCompletions()))
        n = src.resolve_context_window()
        assert n == 65536, f"expected 65536 from /props, got {n}"
    finally:
        urllib.request.urlopen = orig_urlopen


@pytest.mark.sources
@pytest.mark.network
def test_together_over_max_tokens_probe():
    orig_urlopen = urllib.request.urlopen
    def _props_refused(url, timeout=None):
        raise urllib.error.URLError("no /props on remote host")

    urllib.request.urlopen = _props_refused
    try:
        err_msg = ("Error code: 400 - " + json.dumps({
            "error": {"message": "This model's maximum context length is 262144 tokens, "
                      "but the request requires 5000013 tokens."}}))
        src = _make_source(models_page=_FakeModelsPage([]),
                           chat=_FakeChat(_FakeChatCompletions(msg=err_msg)))
        src._context_window = None  # fresh — don't inherit any cached value
        n = src.resolve_context_window()
        assert n == 262144, f"expected 262144 from overrun probe, got {n}"
    finally:
        urllib.request.urlopen = orig_urlopen


@pytest.mark.sources
@pytest.mark.unit
def test_caching_and_force_reprobes():
    err_msg = ("Error code: 400 - " + json.dumps({
        "error": {"message": "This model's maximum context length is 262144 tokens, "
                  "but the request requires 5000013 tokens."}}))
    probe_calls = [0]

    class _CountingChat(_FakeChatCompletions):
        def __init__(self):
            super().__init__(msg=err_msg)
        def create(self, **kwargs):
            probe_calls[0] += 1
            return super().create(**kwargs)

    src = _make_source(models_page=_FakeModelsPage([]),
                       chat=_FakeChat(_CountingChat()))
    src._context_window = None  # ensure fresh
    n1 = src.resolve_context_window()
    n2 = src.resolve_context_window()  # cached
    assert n1 == 262144 and n2 == 262144
    assert probe_calls[0] == 1, f"second call should hit cache, probes={probe_calls[0]}"

    n3 = src.resolve_context_window(force=True)
    assert n3 == 262144 and probe_calls[0] == 2, "force should re-probe"


@pytest.mark.sources
@pytest.mark.network
def test_total_miss_returns_none():
    orig_urlopen = urllib.request.urlopen
    class _NoInfoChat(_FakeChatCompletions):
        def create(self, **kwargs):
            raise RuntimeError("some unrelated error")

    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
        urllib.error.URLError("conn refused"))
    try:
        src = _make_source(models_page=_FakeModelsPage([]),
                           chat=_FakeChat(_NoInfoChat()))
        src._context_window = None
        n = src.resolve_context_window()
        assert n is None, f"expected None on total miss, got {n}"
    finally:
        urllib.request.urlopen = orig_urlopen


@pytest.mark.sources
@pytest.mark.network
def test_remote_source_tries_over_max_tokens_before_v1_models():
    _remote_models_calls = [0]

    class _CountingModels(_FakeModels):
        def list(self, **kwargs):
            _remote_models_calls[0] += 1
            return self._page

    remote_err = ("Error code: 400 - " + json.dumps({
        "error": {"message": "This model's maximum context length is 262144 tokens, "
                  "but the request requires 5000013 tokens."}}))
    remote_page = _FakeModelsPage([_FakeModel("test-model",
                                              {"context_length": 999999})])
    src = m.Source("together", "https://api.together.xyz/v1", "sk-noop",
                   "zai-org/GLM-5.2")
    src.client = _FakeClient(_CountingModels(remote_page),
                             _FakeChat(_FakeChatCompletions(msg=remote_err)))
    src._context_window = None
    n = src.resolve_context_window()
    assert n == 262144, f"remote should resolve via overrun probe, got {n}"
    assert _remote_models_calls[0] == 0, \
        "remote must not hit /v1/models when the overrun probe succeeds"


@pytest.mark.sources
@pytest.mark.unit
def test_is_local_host_classification():
    _local = m.Source("local", "http://localhost:8080/v1", "sk-noop")
    _lan = m.Source("lan", "http://192.168.1.50:8080/v1", "sk-noop")
    _remote1 = m.Source("together", "https://api.together.xyz/v1", "sk-noop")
    _remote2 = m.Source("zai", "https://api.z.ai/api/paas/v4", "sk-noop")
    assert _local._is_local(), "localhost should be local"
    assert _lan._is_local(), "192.168.x should be local"
    assert not _remote1._is_local(), "api.together.xyz should be remote"
    assert not _remote2._is_local(), "api.z.ai should be remote"


@pytest.mark.sources
@pytest.mark.integration
def test_switch_source_invalidates_cached_window():
    global m
    saved_env = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("MINION_"):
            del os.environ[k]
    os.environ["MINION_ENV_FILE"] = "/dev/null"
    os.environ["MINION_SOURCES"] = "alpha,beta"
    os.environ["MINION_SOURCE_ALPHA_BASE_URL"] = "http://localhost:8081/v1"
    os.environ["MINION_SOURCE_BETA_BASE_URL"] = "http://localhost:8082/v1"

    import importlib
    importlib.reload(m)
    try:
        m.SOURCES["alpha"]._context_window = 999
        m.SOURCES["beta"]._context_window = 888
        m.switch_source("alpha")
        assert m.SOURCES["alpha"]._context_window is None, "switch should clear alpha cache"
        m.switch_source("beta")
        assert m.SOURCES["beta"]._context_window is None, "switch should clear beta cache"
    finally:
        for k in list(os.environ):
            if k.startswith("MINION_"):
                del os.environ[k]
        os.environ.update({k: v for k, v in saved_env.items() if k.startswith("MINION_") or k == "MINION_ENV_FILE"})
        importlib.reload(m)


@pytest.mark.sources
@pytest.mark.unit
def test_ctx_field_colorization_by_utilization():
    orig_urlopen = urllib.request.urlopen
    _ANSI = re.compile(r"\x1b\[[0-9;]*m")

    def _plain(s):
        return _ANSI.sub("", s)

    page = _FakeModelsPage([_FakeModel(m.MODEL or "x", {"meta": {"n_ctx": 170000}})])
    src = _make_source(models_page=page, chat=_FakeChat(_FakeChatCompletions()))
    src._context_window = None

    _real_active = m.ACTIVE
    m.ACTIVE = src
    src.resolve_context_window()

    try:
        # Green: under 30% of 170000 (= 51000). Use 667.
        f = m._ctx_field(667)
        assert m.GREEN in f, "under 30% should be green"
        assert m.CYAN in f, "max should be cyan"
        assert "/170K" in _plain(f), "should contain /170K"
        assert "667" in _plain(f), "should contain current 667"

        # Yellow: 30%–60% of 170000 (51000–102000). Use 70000.
        f = m._ctx_field(70000)
        assert m.YELLOW in f and m.GREEN not in f, "30-60% should be yellow, not green"

        # Red: at/above 60% of 170000 (>= 102000). Use 128000 (75%).
        f = m._ctx_field(128000)
        assert m.RED in f and m.YELLOW not in f and m.GREEN not in f, ">=60% should be red only"

        # Unknown max → no color, no slash, just "NNN ctx".
        class _NoInfoChat(_FakeChatCompletions):
            def create(self, **kwargs):
                raise RuntimeError("some unrelated error")

        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("no /props"))
        src2 = _make_source(models_page=_FakeModelsPage([]),
                            chat=_FakeChat(_NoInfoChat()))
        src2._context_window = None
        m.ACTIVE = src2

        f = m._ctx_field(1234)
        assert m.GREEN not in f and m.CYAN not in f and m.RED not in f, "no color when max unknown"
        assert "/" not in _plain(f), "no slash when max unknown"
        assert "1.2K" in _plain(f) and "ctx" in _plain(f), "should still show current + 'ctx'"
    finally:
        m.ACTIVE = _real_active
        urllib.request.urlopen = orig_urlopen


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))