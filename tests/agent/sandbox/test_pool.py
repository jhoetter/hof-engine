"""ContainerPool lifecycle: in-use tracking, orphan reaper, atexit, background reaper."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hof.agent.sandbox.pool import (
    _POOL_ID_LABEL,
    _SANDBOX_LABEL,
    ContainerPool,
    _reset_module_state,
    get_container_pool,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_container(cid: str = "abc123", *, labels: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.id = cid
    c.labels = labels or {}
    return c


def _pool_kwargs(**overrides) -> dict:
    defaults = dict(
        image="test:latest",
        pool_size=2,
        network_mode="bridge",
        memory_limit="256m",
        cpu_period=100_000,
        cpu_quota=100_000,
        pool_max_idle_sec=600,
    )
    defaults.update(overrides)
    return defaults


def _sandbox_config(**overrides) -> SimpleNamespace:
    kw = _pool_kwargs(**overrides)
    return SimpleNamespace(**kw)


# ---------------------------------------------------------------------------
# ContainerPool unit tests
# ---------------------------------------------------------------------------


class TestContainerPoolLabels:
    """Containers are tagged with Docker labels for ownership tracking."""

    @patch("hof.agent.sandbox.pool.docker")
    def test_create_container_sets_labels(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client
        mock_docker.errors.DockerException = Exception
        mock_docker.errors.ImageNotFound = Exception
        mock_docker.errors.NotFound = Exception

        fake = _fake_container("cid1")
        client.containers.run.return_value = fake

        pool = ContainerPool(**_pool_kwargs(pool_size=1))
        pool.ensure_pool()

        run_call = client.containers.run.call_args
        labels = run_call.kwargs.get("labels") or run_call[1].get("labels")
        assert labels[_SANDBOX_LABEL] == "true"
        assert _POOL_ID_LABEL in labels
        assert len(labels[_POOL_ID_LABEL]) == 16


class TestContainerPoolInUseTracking:
    """Acquired containers are tracked in ``_in_use`` and cleaned up on shutdown."""

    @patch("hof.agent.sandbox.pool.docker")
    def test_acquire_tracks_in_use(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        pool = ContainerPool(**_pool_kwargs(pool_size=1))
        fake = _fake_container("cid-acq")
        client.containers.run.return_value = fake

        pool.ensure_pool()
        pc = pool.acquire()

        assert pc.container_id == "cid-acq"
        assert "cid-acq" in pool._in_use
        assert len(pool._idle) == 0

    @patch("hof.agent.sandbox.pool.docker")
    def test_release_removes_from_in_use(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        pool = ContainerPool(**_pool_kwargs(pool_size=2))
        fake = _fake_container("cid-rel")
        client.containers.run.return_value = fake
        client.containers.get.return_value = fake

        pool.ensure_pool()
        assert len(pool._idle) == 2
        pc = pool.acquire()
        assert "cid-rel" in pool._in_use
        assert len(pool._idle) == 1

        pool.release(pc, reset_workspace=False)
        assert "cid-rel" not in pool._in_use
        assert len(pool._idle) == 2

    @patch("hof.agent.sandbox.pool.docker")
    def test_shutdown_cleans_both_idle_and_in_use(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        containers = {}
        call_count = 0

        def make_container(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            cid = f"cid-{call_count}"
            c = _fake_container(cid)
            containers[cid] = c
            return c

        client.containers.run.side_effect = make_container
        client.containers.get.side_effect = lambda cid: containers.get(cid, _fake_container(cid))

        pool = ContainerPool(**_pool_kwargs(pool_size=2))
        pool.ensure_pool()
        _acquired = pool.acquire()  # noqa: F841

        assert len(pool._idle) == 1
        assert len(pool._in_use) == 1

        pool.shutdown()

        assert len(pool._idle) == 0
        assert len(pool._in_use) == 0
        stop_calls = sum(c.stop.call_count for c in containers.values())
        assert stop_calls >= 2

    @patch("hof.agent.sandbox.pool.docker")
    def test_acquire_after_shutdown_raises(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        pool = ContainerPool(**_pool_kwargs())
        pool.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            pool.acquire()

    @patch("hof.agent.sandbox.pool.docker")
    def test_release_after_shutdown_destroys(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        fake = _fake_container("cid-late")
        client.containers.run.return_value = fake
        client.containers.get.return_value = fake

        pool = ContainerPool(**_pool_kwargs(pool_size=1))
        pool.ensure_pool()
        pc = pool.acquire()

        pool.shutdown()
        pool.release(pc)

        fake.stop.assert_called()
        assert len(pool._idle) == 0


class TestContainerPoolReaper:
    """Background reaper daemon evicts stale idle containers."""

    @patch("hof.agent.sandbox.pool._REAPER_INTERVAL_SEC", 0.05)
    @patch("hof.agent.sandbox.pool.docker")
    def test_reaper_thread_starts_and_reaps(self, mock_docker):
        client = MagicMock()
        mock_docker.from_env.return_value = client

        fake = _fake_container("cid-reap")
        client.containers.run.return_value = fake
        client.containers.get.return_value = fake

        pool = ContainerPool(**_pool_kwargs(pool_size=1, pool_max_idle_sec=60))
        pool.ensure_pool()
        assert len(pool._idle) == 1

        pool._idle[0].created_at = time.monotonic() - 9999

        pool.start_reaper()
        assert pool._reaper_thread is not None
        assert pool._reaper_thread.daemon is True

        time.sleep(0.2)

        assert len(pool._idle) == 0
        fake.stop.assert_called()

        pool.shutdown()


# ---------------------------------------------------------------------------
# Module-level lifecycle (orphan reaper, atexit, get_container_pool)
# ---------------------------------------------------------------------------


class TestOrphanReaper:
    """Startup orphan reaper removes containers from previous processes."""

    @patch("hof.agent.sandbox.pool.docker")
    def test_get_container_pool_reaps_orphans_on_first_call(self, mock_docker):
        _reset_module_state()

        client = MagicMock()
        mock_docker.from_env.return_value = client

        orphan = _fake_container("orphan-1", labels={_SANDBOX_LABEL: "true"})
        client.containers.list.return_value = [orphan]
        client.containers.run.return_value = _fake_container("new-1")

        cfg = _sandbox_config()
        pool = get_container_pool(cfg)

        # Orphan reaping + pre-warming run in a background thread; wait for it.
        for t in threading.enumerate():
            if t.name == "hof-sandbox-init":
                t.join(timeout=5)

        label_filter_calls = [c for c in client.containers.list.call_args_list if "label" in str(c)]
        assert len(label_filter_calls) >= 1

        orphan.stop.assert_called()
        orphan.remove.assert_called()

        pool.shutdown()
        _reset_module_state()

    @patch("hof.agent.sandbox.pool.docker")
    def test_get_container_pool_second_call_skips_reap(self, mock_docker):
        _reset_module_state()

        client = MagicMock()
        mock_docker.from_env.return_value = client
        client.containers.list.return_value = []
        client.containers.run.return_value = _fake_container("p1")

        cfg = _sandbox_config()
        pool1 = get_container_pool(cfg)

        # Wait for background init thread to finish before resetting mock.
        for t in threading.enumerate():
            if t.name == "hof-sandbox-init":
                t.join(timeout=5)

        client.containers.list.reset_mock()

        pool2 = get_container_pool(cfg)
        assert pool1 is pool2
        client.containers.list.assert_not_called()

        pool1.shutdown()
        _reset_module_state()


class TestAtexitHandler:
    """atexit handler is registered and calls shutdown."""

    @patch("hof.agent.sandbox.pool.atexit")
    @patch("hof.agent.sandbox.pool.docker")
    def test_atexit_registered_on_first_pool(self, mock_docker, mock_atexit):
        _reset_module_state()

        client = MagicMock()
        mock_docker.from_env.return_value = client
        client.containers.list.return_value = []
        client.containers.run.return_value = _fake_container("at1")

        cfg = _sandbox_config()
        pool = get_container_pool(cfg)

        mock_atexit.register.assert_called_once()

        # Wait for background init before shutdown to avoid thread races.
        for t in threading.enumerate():
            if t.name == "hof-sandbox-init":
                t.join(timeout=5)

        pool.shutdown()
        _reset_module_state()
