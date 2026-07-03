#!/usr/bin/env python3
"""Smoke test for minion's multi-source system. No live server needed."""
import os, sys, importlib

# Add project root (parent of this tests/ dir) to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def clear_minion_env():
    for k in list(os.environ):
        if k.startswith("MINION_"):
            del os.environ[k]
    # Scrub the built-in `together` source's trigger key so tests that want a
    # known, minimal source set aren't perturbed by a real ~/.env / shell
    # export of TOGETHER_API_KEY. (Tests that exercise the together source
    # set it explicitly.)
    os.environ.pop("TOGETHER_API_KEY", None)
    # Prevent ~/.env from leaking real config into the tests. _load_env_file()
    # re-reads it on every reload, so point it at a nonexistent file.
    os.environ["MINION_ENV_FILE"] = "/dev/null"


def test_legacy_fallback():
    clear_minion_env()
    sys.argv = ["minion.py"]
    import minion
    importlib.reload(minion)
    
    assert list(minion.SOURCES.keys()) == ["local"]
    assert minion.ACTIVE.name == "local"
    assert minion.client.base_url == "http://localhost:8080/v1/"


def test_multi_source_discovery():
    clear_minion_env()
    os.environ["MINION_SOURCES"] = "local,zai"
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_SOURCE_LOCAL_API_KEY"] = "sk-noop"
    os.environ["ZAI_TEST_KEY"] = "fake-zai-key-12345"
    os.environ["MINION_SOURCE_ZAI_BASE_URL"] = "https://api.z.ai/api/paas/v4"
    os.environ["MINION_SOURCE_ZAI_API_KEY"] = "$ZAI_TEST_KEY"
    os.environ["MINION_SOURCE_ZAI_MODEL"] = "glm-x-preview"
    sys.argv = ["minion.py"]
    
    import minion
    importlib.reload(minion)
    
    assert minion.SOURCE_ORDER == ["local", "zai"]
    assert minion.ACTIVE.name == "local"
    assert minion.SOURCES["zai"].api_key == "fake-zai-key-12345"
    assert minion.SOURCES["zai"].model == "glm-x-preview"
    assert minion.SOURCES["local"].model is None


def test_switch_source():
    clear_minion_env()
    os.environ["MINION_SOURCES"] = "local,zai"
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_SOURCE_ZAI_BASE_URL"] = "https://api.z.ai/api/paas/v4"
    os.environ["MINION_SOURCE_ZAI_MODEL"] = "glm-x-preview"
    sys.argv = ["minion.py"]
    
    import minion
    importlib.reload(minion)
    
    # test switch
    old_client_id = id(minion.client)
    minion.switch_source("zai")
    assert minion.ACTIVE.name == "zai"
    assert minion.MODEL == "glm-x-preview"
    assert id(minion.client) != old_client_id
    
    # test switch back
    minion.switch_source("local")
    assert minion.ACTIVE.name == "local"
    
    # test unknown source
    result = minion.switch_source("nonexistent")
    assert result is False


def test_source_flag():
    clear_minion_env()
    os.environ["MINION_SOURCES"] = "local,zai"
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_SOURCE_ZAI_BASE_URL"] = "https://api.z.ai/api/paas/v4"
    os.environ["MINION_SOURCE_ZAI_MODEL"] = "glm-x-preview"
    sys.argv = ["minion.py", "--source", "zai"]
    
    import minion
    importlib.reload(minion)
    assert minion.ACTIVE.name == "zai"


def test_auto_discover_from_base_url():
    clear_minion_env()
    sys.argv = ["minion.py"]
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_SOURCE_ZAI_BASE_URL"] = "https://api.z.ai/api/paas/v4"
    
    import minion
    importlib.reload(minion)
    assert set(minion.SOURCE_ORDER) == {"local", "zai"}


def test_banner_with_multiple_sources():
    clear_minion_env()
    os.environ["MINION_SOURCES"] = "local,zai"
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["MINION_SOURCE_ZAI_BASE_URL"] = "https://api.z.ai/api/paas/v4"
    sys.argv = ["minion.py"]
    
    import minion
    importlib.reload(minion)
    minion.switch_source("zai")
    banner = minion._banner()
    assert "zai" in banner


def test_together_source_auto_register():
    clear_minion_env()
    sys.argv = ["minion.py"]
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    os.environ["TOGETHER_API_KEY"] = "fake-together-key"
    
    import minion
    importlib.reload(minion)
    assert "together" in minion.SOURCES
    assert minion.SOURCES["together"].base_url == "https://api.together.xyz/v1"
    assert minion.SOURCES["together"].model == "zai-org/GLM-5.2"
    assert minion.SOURCES["together"].api_key == "fake-together-key"
    assert minion.SOURCE_ORDER[0] == "local"
    assert minion.SOURCE_ORDER[-1] == "together"
    assert minion.ACTIVE.name == "local"


def test_no_together_source_without_key():
    clear_minion_env()
    sys.argv = ["minion.py"]
    os.environ["MINION_SOURCE_LOCAL_BASE_URL"] = "http://localhost:8080/v1"
    
    import minion
    importlib.reload(minion)
    assert "together" not in minion.SOURCES


def test_together_config_override():
    clear_minion_env()
    sys.argv = ["minion.py"]
    os.environ["MINION_SOURCES"] = "together"
    os.environ["MINION_SOURCE_TOGETHER_BASE_URL"] = "https://my-proxy.example/v1"
    os.environ["MINION_SOURCE_TOGETHER_API_KEY"] = "custom-key"
    os.environ["MINION_SOURCE_TOGETHER_MODEL"] = "my-org/my-model"
    os.environ["TOGETHER_API_KEY"] = "fake-together-key"
    
    import minion
    importlib.reload(minion)
    assert minion.SOURCES["together"].base_url == "https://my-proxy.example/v1"
    assert minion.SOURCES["together"].model == "my-org/my-model"
    assert minion.SOURCES["together"].api_key == "custom-key"


def test_switch_source_model_override():
    clear_minion_env()
    sys.argv = ["minion.py"]
    os.environ["MINION_SOURCES"] = "together"
    os.environ["MINION_SOURCE_TOGETHER_BASE_URL"] = "https://api.together.xyz/v1"
    os.environ["MINION_SOURCE_TOGETHER_API_KEY"] = "k"
    os.environ["MINION_SOURCE_TOGETHER_MODEL"] = "zai-org/GLM-5.2"
    
    import minion
    importlib.reload(minion)
    minion.switch_source("together")
    assert minion.MODEL == "zai-org/GLM-5.2"
    
    minion.switch_source("together", model_override="zai-org/GLM-4.6")
    assert minion.MODEL == "zai-org/GLM-4.6"
    
    minion.switch_source("together")
    assert minion.MODEL == "zai-org/GLM-5.2"
