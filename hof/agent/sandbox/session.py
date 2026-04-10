"""Per-run terminal session: docker exec with timeout and output limits."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

from hof.agent.sandbox.pool import ContainerPool, _PooledContainer

logger = logging.getLogger(__name__)

_DOCKER_EXEC_USER = "sandbox"


@dataclass(frozen=True)
class TerminalResult:
    exit_code: int
    output: str


class TerminalSession:
    """Binds one pooled container for sequential ``exec`` calls."""

    def __init__(
        self,
        *,
        pool: ContainerPool,
        pooled: _PooledContainer,
        workdir: str,
        environment: dict[str, str],
        max_output_chars: int,
        max_timeout_sec: int,
    ) -> None:
        self._pool = pool
        self._pooled = pooled
        self._workdir = workdir
        self._environment = environment
        self._max_output_chars = max(256, max_output_chars)
        self._max_timeout_sec = max(1, max_timeout_sec)
        self._released = False

    @property
    def container_id(self) -> str:
        return self._pooled.container_id

    def exec_command(
        self,
        command: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> TerminalResult:
        """Run ``command`` in the container (bash -lc). Merges stdout+stderr.

        ``extra_env`` is merged into the session environment for this invocation only
        (e.g. per-exec ``HOF_AGENT_RUN_ID`` / ``HOF_AGENT_TOOL_CALL_ID``).
        """
        if self._released:
            return TerminalResult(1, "error: sandbox session already released")

        merged = {**self._environment, **(extra_env or {})}
        env_file = None
        try:
            if merged:
                fd, env_file = tempfile.mkstemp(prefix="hof-sandbox-env-", suffix=".env", text=True)
                try:
                    with os.fdopen(fd, "w") as f:
                        for k, v in merged.items():
                            f.write(f"{k}={v}\n")
                except Exception:
                    os.close(fd)
                    raise

            cmd = ["docker", "exec", "-i", "-u", _DOCKER_EXEC_USER]
            if env_file:
                cmd.extend(["--env-file", env_file])
            cmd.extend(["-w", self._workdir, self._pooled.container_id, "bash", "-lc", command])

            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=float(self._max_timeout_sec),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return TerminalResult(124, "error: command timed out")
        except FileNotFoundError:
            return TerminalResult(127, "error: docker CLI not found on PATH")
        except Exception as exc:
            logger.exception("sandbox exec failed")
            return TerminalResult(1, f"error: {exc}")
        finally:
            if env_file:
                try:
                    os.unlink(env_file)
                except Exception:
                    pass

        out_b = (proc.stdout or b"") + (proc.stderr or b"")
        text = out_b.decode("utf-8", errors="replace")
        if len(text) > self._max_output_chars:
            text = text[: self._max_output_chars - 24] + "\n…(truncated)"
        return TerminalResult(proc.returncode, text)

    def release(self, *, reset_workspace: bool = True) -> None:
        if self._released:
            return
        self._released = True
        self._pool.release(self._pooled, reset_workspace=reset_workspace)


def create_session_for_run(
    pool: ContainerPool,
    *,
    workdir: str,
    environment: dict[str, str],
    max_output_chars: int,
    max_timeout_sec: int,
) -> TerminalSession:
    pool.ensure_pool()
    pooled = pool.acquire()
    return TerminalSession(
        pool=pool,
        pooled=pooled,
        workdir=workdir,
        environment=environment,
        max_output_chars=max_output_chars,
        max_timeout_sec=max_timeout_sec,
    )
