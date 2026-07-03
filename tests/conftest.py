"""Shared fixtures for the minion test suite.

Eliminates per-file boilerplate for:
  - Temp directory creation (MINION_SESSIONS_DIR / MINION_HOME)
  - sys.path injection so ``import minion`` works
  - A helper to reset the minion module between tests (isolates state)
"""

import os
import shutil
import sys
import tempfile

import pytest

# Ensure the project root (parent of tests/) is on sys.path once, globally.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


@pytest.fixture()
def tmp_minion():
    """Create a throwaway temp directory and point MINION env vars at it.

    Yields the directory path.  Cleans up the directory after the test.
    Also resets ``minion._sessions_dir`` cache so tests don't share stale paths.
    """
    import minion  # noqa: PLC0415 (import here to get fresh module)

    tmp_dir = tempfile.mkdtemp(prefix="minion-test-")
    env_backup = {}
    for key in ("MINION_SESSIONS_DIR", "MINION_HOME"):
        env_backup[key] = os.environ.get(key)
        os.environ[key] = tmp_dir

    # Clear minion's internal caches that persist across tests.
    if hasattr(minion, "_sessions_dir_cache"):
        minion._sessions_dir_cache.clear()

    try:
        yield tmp_dir
    finally:
        # Restore env
        for key, val in env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
        # Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def minion_session_dir(tmp_minion):
    """Alias: returns the temp session directory path (same as tmp_minion)."""
    return tmp_minion


def pytest_configure(config):
    """Ensure project root is always on sys.path for tests."""
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
