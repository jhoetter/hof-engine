"""Pooled Docker containers for sandbox terminal execution."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

try:
    import docker
    from docker.errors import DockerException, ImageNotFound, NotFound
except ImportError:  # pragma: no cover - optional dependency
    docker = None  # type: ignore[assignment]
    DockerException = Exception  # type: ignore[misc, assignment]
    ImageNotFound = NotFound = Exception  # type: ignore[misc, assignment]


class _PooledContainer:
    __slots__ = ("container_id", "created_at")

    def __init__(self, *, container_id: str, created_at: float) -> None:
        self.container_id = container_id
        self.created_at = created_at


class ContainerPool:
    """In-process pool of long-running containers; ``exec`` per command."""

    def __init__(
        self,
        *,
        image: str,
        pool_size: int,
        network_mode: str,
        memory_limit: str,
        cpu_period: int,
        cpu_quota: int,
        pool_max_idle_sec: int,
    ) -> None:
        self._image = image
        self._pool_size = max(1, pool_size)
        self._network_mode = network_mode
        self._memory_limit = memory_limit
        self._cpu_period = cpu_period
        self._cpu_quota = cpu_quota
        self._pool_max_idle_sec = max(60, pool_max_idle_sec)
        self._lock = threading.Lock()
        self._idle: list[_PooledContainer] = []

    def _client(self) -> Any:
        if docker is None:
            msg = (
                "docker package is not installed; add `docker` to dependencies for sandbox support"
            )
            raise RuntimeError(msg)
        return docker.from_env()

    def ensure_pool(self) -> None:
        """Create idle containers up to ``pool_size`` (best-effort)."""
        with self._lock:
            self._reap_unlocked()
            need = self._pool_size - len(self._idle)
            for _ in range(max(0, need)):
                try:
                    pc = self._create_container_unlocked()
                    self._idle.append(pc)
                except Exception:
                    logger.exception("sandbox pool: failed to create container")
                    break

    def _create_container_unlocked(self) -> _PooledContainer:
        client = self._client()
        name = f"hof-sandbox-{uuid.uuid4().hex[:12]}"
        # So ``host.docker.internal`` resolves inside the container (Mac/Win Docker Desktop;
        # Linux Docker 20.10+ with ``host-gateway``). Skip for ``host`` network mode.
        run_kw: dict[str, Any] = {
            "command": ["sleep", "infinity"],
            "detach": True,
            "name": name,
            "network_mode": self._network_mode,
            "mem_limit": self._memory_limit,
            "cpu_period": self._cpu_period,
            "cpu_quota": self._cpu_quota,
            "remove": False,
        }
        if self._network_mode != "host":
            run_kw["extra_hosts"] = {"host.docker.internal": "host-gateway"}
        container = client.containers.run(self._image, **run_kw)
        return _PooledContainer(container_id=container.id, created_at=time.monotonic())

    def _reap_unlocked(self) -> None:
        now = time.monotonic()
        kept: list[_PooledContainer] = []
        client = self._client()
        for pc in self._idle:
            if now - pc.created_at > self._pool_max_idle_sec:
                try:
                    c = client.containers.get(pc.container_id)
                    c.stop(timeout=5)
                    c.remove(force=True)
                except NotFound:
                    pass
                except Exception:
                    logger.debug("sandbox pool: remove stale container failed", exc_info=True)
            else:
                kept.append(pc)
        self._idle = kept

    def acquire(self) -> _PooledContainer:
        """Return a container handle; may create one synchronously if pool empty."""
        with self._lock:
            self._reap_unlocked()
            if self._idle:
                return self._idle.pop()
        with self._lock:
            try:
                return self._create_container_unlocked()
            except ImageNotFound:
                logger.exception(
                    "sandbox pool: image %r not found — build skill image or set HOF_SANDBOX_IMAGE",
                    self._image,
                )
                raise
            except DockerException:
                logger.exception("sandbox pool: docker error creating container")
                raise

    def release(self, pc: _PooledContainer, *, reset_workspace: bool = True) -> None:
        """Reset workspace and return container to the pool, or destroy if pool full."""
        client = self._client()
        if reset_workspace:
            try:
                c = client.containers.get(pc.container_id)
                c.exec_run(
                    [
                        "bash",
                        "-lc",
                        "shopt -s dotglob; rm -rf /workspace/* /tmp/* 2>/dev/null || true",
                    ],
                )
            except NotFound:
                return
            except Exception:
                logger.debug("sandbox pool: workspace reset failed", exc_info=True)
                self._destroy_container(pc)
                return
        pc.created_at = time.monotonic()
        with self._lock:
            self._reap_unlocked()
            if len(self._idle) < self._pool_size:
                self._idle.append(pc)
            else:
                self._destroy_container_unlocked(pc, client)

    def _destroy_container(self, pc: _PooledContainer) -> None:
        try:
            client = self._client()
            self._destroy_container_unlocked(pc, client)
        except Exception:
            logger.debug("sandbox pool: destroy failed", exc_info=True)

    def _destroy_container_unlocked(self, pc: _PooledContainer, client: Any) -> None:
        try:
            c = client.containers.get(pc.container_id)
            c.stop(timeout=5)
            c.remove(force=True)
        except NotFound:
            return
        except Exception:
            logger.debug("sandbox pool: destroy failed", exc_info=True)

    def shutdown(self) -> None:
        """Shutdown the pool by stopping and removing all idle containers."""
        with self._lock:
            client = self._client()
            for pc in self._idle:
                try:
                    c = client.containers.get(pc.container_id)
                    c.stop(timeout=5)
                    c.remove(force=True)
                except NotFound:
                    pass
                except Exception:
                    logger.debug("sandbox pool: shutdown failed for container", exc_info=True)
            self._idle.clear()


_pool_lock = threading.Lock()
_global_pool: ContainerPool | None = None
_global_pool_key: tuple[Any, ...] | None = None


def get_container_pool(config: Any) -> ContainerPool:
    """Return a process-wide pool for the given resolved :class:`SandboxConfig`."""
    global _global_pool, _global_pool_key
    key = (
        config.image,
        config.pool_size,
        config.network_mode,
        config.memory_limit,
        config.cpu_period,
        config.cpu_quota,
        config.pool_max_idle_sec,
    )
    with _pool_lock:
        if _global_pool is not None and _global_pool_key == key:
            return _global_pool
        old_pool = _global_pool
        _global_pool = ContainerPool(
            image=config.image,
            pool_size=config.pool_size,
            network_mode=config.network_mode,
            memory_limit=config.memory_limit,
            cpu_period=config.cpu_period,
            cpu_quota=config.cpu_quota,
            pool_max_idle_sec=config.pool_max_idle_sec,
        )
        _global_pool_key = key
        if old_pool is not None:
            old_pool.shutdown()
        return _global_pool
