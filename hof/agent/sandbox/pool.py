"""Pooled Docker containers for sandbox terminal execution.

Lifecycle guarantees
--------------------
* **Startup orphan reaper** — ``_reap_orphans()`` removes every ``hof-sandbox-*``
  container from previous processes so they never accumulate across restarts.
  Runs in a **background thread** so it never blocks the first request.
* **atexit handler** — ``shutdown()`` is registered via :func:`atexit.register`
  so idle *and* in-use containers are cleaned up on graceful exit.
* **Background reaper** — a daemon thread periodically evicts idle containers
  that exceed ``pool_max_idle_sec`` even when no ``acquire``/``release`` traffic
  flows through the pool.
* **Background pre-warming** — right after pool creation, ``ensure_pool()``
  runs in a background thread so warm containers are ready before the first
  request, without blocking ``get_container_pool()``.
* **Docker labels** — every container is tagged with ``hof.sandbox=true`` and a
  per-pool ``hof.sandbox.pool_id`` so the reaper can filter efficiently.
"""

from __future__ import annotations

import atexit
import concurrent.futures
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

_SANDBOX_LABEL = "hof.sandbox"
_POOL_ID_LABEL = "hof.sandbox.pool_id"
_CONTAINER_NAME_PREFIX = "hof-sandbox-"

_REAPER_INTERVAL_SEC = 60


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
        self._pool_id = uuid.uuid4().hex[:16]
        self._lock = threading.Lock()
        self._idle: list[_PooledContainer] = []
        self._in_use: dict[str, _PooledContainer] = {}
        self._shutdown = False
        self._reaper_thread: threading.Thread | None = None

    def _client(self) -> Any:
        if docker is None:
            msg = (
                "docker package is not installed; add `docker` to dependencies for sandbox support"
            )
            raise RuntimeError(msg)
        return docker.from_env()

    # -- public API -----------------------------------------------------------

    def ensure_pool(self) -> None:
        """Create idle containers up to ``pool_size`` (best-effort, parallel)."""
        with self._lock:
            if self._shutdown:
                return
            self._reap_idle_unlocked()
            need = self._pool_size - len(self._idle)
        if need <= 0:
            return
        if need == 1:
            try:
                pc = self._create_container_unlocked()
                with self._lock:
                    if not self._shutdown:
                        self._idle.append(pc)
                    else:
                        self._destroy_container_quiet(pc)
            except Exception:
                logger.exception("sandbox pool: failed to create container")
            return
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=need,
            thread_name_prefix="hof-sandbox-warm",
        ) as ex:
            futs = [ex.submit(self._create_container_unlocked) for _ in range(need)]
            for fut in concurrent.futures.as_completed(futs):
                try:
                    pc = fut.result()
                    with self._lock:
                        if not self._shutdown:
                            self._idle.append(pc)
                        else:
                            self._destroy_container_quiet(pc)
                except Exception:
                    logger.exception("sandbox pool: failed to create container")

    def acquire(self) -> _PooledContainer:
        """Return a container handle; may create one synchronously if pool empty."""
        with self._lock:
            if self._shutdown:
                raise RuntimeError("sandbox pool is shut down")
            self._reap_idle_unlocked()
            if self._idle:
                pc = self._idle.pop()
                self._in_use[pc.container_id] = pc
                return pc
        with self._lock:
            if self._shutdown:
                raise RuntimeError("sandbox pool is shut down")
            try:
                pc = self._create_container_unlocked()
                self._in_use[pc.container_id] = pc
                return pc
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
        with self._lock:
            self._in_use.pop(pc.container_id, None)
            if self._shutdown:
                self._destroy_container_quiet(pc)
                return
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
                self._destroy_container_quiet(pc)
                return
        pc.created_at = time.monotonic()
        with self._lock:
            if self._shutdown:
                self._destroy_container_quiet(pc)
                return
            self._reap_idle_unlocked()
            if len(self._idle) < self._pool_size:
                self._idle.append(pc)
            else:
                self._destroy_container_unlocked(pc, client)

    def shutdown(self) -> None:
        """Stop and remove all containers (idle + in-use). Idempotent."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            all_containers = list(self._idle) + list(self._in_use.values())
            self._idle.clear()
            self._in_use.clear()
        client = self._client()
        for pc in all_containers:
            try:
                c = client.containers.get(pc.container_id)
                c.stop(timeout=5)
                c.remove(force=True)
            except NotFound:
                pass
            except Exception:
                logger.debug("sandbox pool: shutdown failed for container", exc_info=True)

    def start_reaper(self) -> None:
        """Start the background reaper daemon thread (idempotent)."""
        with self._lock:
            if self._reaper_thread is not None:
                return
            t = threading.Thread(target=self._reaper_loop, daemon=True, name="hof-sandbox-reaper")
            self._reaper_thread = t
            t.start()

    # -- internal helpers -----------------------------------------------------

    def _create_container_unlocked(self) -> _PooledContainer:
        client = self._client()
        name = f"{_CONTAINER_NAME_PREFIX}{uuid.uuid4().hex[:12]}"
        labels = {_SANDBOX_LABEL: "true", _POOL_ID_LABEL: self._pool_id}
        run_kw: dict[str, Any] = {
            "command": ["sleep", "infinity"],
            "detach": True,
            "name": name,
            "labels": labels,
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

    def _reap_idle_unlocked(self) -> None:
        """Remove idle containers that have exceeded ``pool_max_idle_sec``."""
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

    def _destroy_container_quiet(self, pc: _PooledContainer) -> None:
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

    def _reaper_loop(self) -> None:
        """Daemon thread that periodically evicts expired idle containers."""
        while not self._shutdown:
            time.sleep(_REAPER_INTERVAL_SEC)
            if self._shutdown:
                break
            try:
                with self._lock:
                    self._reap_idle_unlocked()
            except Exception:
                logger.debug("sandbox reaper: tick failed", exc_info=True)


# -- module-level singleton + lifecycle ---------------------------------------

_pool_lock = threading.Lock()
_global_pool: ContainerPool | None = None
_global_pool_key: tuple[Any, ...] | None = None
_atexit_registered = False


def _reap_orphans(image: str) -> None:
    """Remove **all** ``hof-sandbox-*`` containers from previous processes.

    Called once when the first pool is created in this process. Uses Docker
    label filtering so only containers we created are touched.
    """
    if docker is None:
        return
    try:
        client = docker.from_env()
        orphans = client.containers.list(
            all=True,
            filters={"label": f"{_SANDBOX_LABEL}=true"},
        )
        if not orphans:
            return
        logger.info(
            "sandbox pool: cleaning up %d orphaned containers from previous runs",
            len(orphans),
        )
        for c in orphans:
            try:
                c.stop(timeout=5)
            except Exception:
                pass
            try:
                c.remove(force=True)
            except NotFound:
                pass
            except Exception:
                logger.debug("sandbox pool: orphan removal failed for %s", c.id[:12], exc_info=True)
    except Exception:
        logger.debug("sandbox pool: orphan reap failed", exc_info=True)


def _reap_orphans_by_name() -> None:
    """Fallback: remove containers matching the ``hof-sandbox-`` name prefix.

    Catches containers created before labels were added (upgrade path).
    """
    if docker is None:
        return
    try:
        client = docker.from_env()
        orphans = client.containers.list(
            all=True,
            filters={"name": _CONTAINER_NAME_PREFIX},
        )
        unlabeled = [c for c in orphans if c.labels.get(_SANDBOX_LABEL) != "true"]
        if not unlabeled:
            return
        logger.info(
            "sandbox pool: cleaning up %d legacy (unlabeled) orphaned containers",
            len(unlabeled),
        )
        for c in unlabeled:
            try:
                c.stop(timeout=5)
            except Exception:
                pass
            try:
                c.remove(force=True)
            except NotFound:
                pass
            except Exception:
                logger.debug("sandbox pool: legacy orphan removal failed", exc_info=True)
    except Exception:
        logger.debug("sandbox pool: legacy orphan reap failed", exc_info=True)


def _atexit_shutdown() -> None:
    """Called by :func:`atexit.register` to drain all containers on process exit."""
    global _global_pool
    with _pool_lock:
        pool = _global_pool
        _global_pool = None
    if pool is not None:
        try:
            pool.shutdown()
        except Exception:
            pass


def _background_orphan_reap_and_warm(image: str, pool: ContainerPool) -> None:
    """Run orphan cleanup then pre-warm the pool, all off the request path."""
    _reap_orphans(image)
    _reap_orphans_by_name()
    try:
        pool.ensure_pool()
    except Exception:
        logger.debug("sandbox pool: background pre-warm failed", exc_info=True)


def get_container_pool(config: Any) -> ContainerPool:
    """Return a process-wide pool for the given resolved :class:`SandboxConfig`."""
    global _global_pool, _global_pool_key, _atexit_registered
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

        first_pool = old_pool is None and not _atexit_registered

        pool = ContainerPool(
            image=config.image,
            pool_size=config.pool_size,
            network_mode=config.network_mode,
            memory_limit=config.memory_limit,
            cpu_period=config.cpu_period,
            cpu_quota=config.cpu_quota,
            pool_max_idle_sec=config.pool_max_idle_sec,
        )
        _global_pool = pool
        _global_pool_key = key
        pool.start_reaper()

        if first_pool:
            atexit.register(_atexit_shutdown)
            _atexit_registered = True
            t = threading.Thread(
                target=_background_orphan_reap_and_warm,
                args=(config.image, pool),
                daemon=True,
                name="hof-sandbox-init",
            )
            t.start()
        else:
            t = threading.Thread(
                target=pool.ensure_pool,
                daemon=True,
                name="hof-sandbox-warm",
            )
            t.start()

        if old_pool is not None:
            old_pool.shutdown()
        return pool


def _reset_module_state() -> None:
    """Reset global pool state. **Test helper only** — not for production use."""
    global _global_pool, _global_pool_key, _atexit_registered
    with _pool_lock:
        pool = _global_pool
        _global_pool = None
        _global_pool_key = None
        _atexit_registered = False
    if pool is not None:
        pool.shutdown()
