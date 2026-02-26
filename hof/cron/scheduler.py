"""Cron job decorator and scheduling via Celery Beat."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Callable

from hof.core.registry import registry


@dataclass
class CronMetadata:
    """Metadata about a registered cron job."""

    name: str
    schedule: str
    fn: Callable
    timezone: str = "UTC"
    retries: int = 0
    timeout: int = 300
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "schedule": self.schedule,
            "timezone": self.timezone,
            "retries": self.retries,
            "timeout": self.timeout,
            "enabled": self.enabled,
        }


def cron(
    schedule: str,
    *,
    timezone: str = "UTC",
    retries: int = 0,
    timeout: int = 300,
    enabled: bool = True,
) -> Callable:
    """Register a function as a cron job.

    Args:
        schedule: Cron expression (e.g., "0 2 * * *" for daily at 2 AM).
        timezone: Timezone for the schedule (default: UTC).
        retries: Number of retries on failure.
        timeout: Max execution time in seconds.
        enabled: Whether the cron job is active.
    """

    def decorator(fn: Callable) -> Callable:
        metadata = CronMetadata(
            name=fn.__name__,
            schedule=schedule,
            fn=fn,
            timezone=timezone,
            retries=retries,
            timeout=timeout,
            enabled=enabled,
        )
        registry.register_cron(metadata)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper._hof_cron = metadata  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_celery_beat_schedule() -> dict:
    """Build the Celery Beat schedule from registered cron jobs."""
    from celery.schedules import crontab

    schedule = {}
    for name, meta in registry.cron_jobs.items():
        if not meta.enabled:
            continue

        parts = meta.schedule.split()
        if len(parts) != 5:
            continue

        minute, hour, day_of_month, month_of_year, day_of_week = parts

        schedule[f"hof-cron-{name}"] = {
            "task": "hof.execute_cron",
            "schedule": crontab(
                minute=minute,
                hour=hour,
                day_of_month=day_of_month,
                month_of_year=month_of_year,
                day_of_week=day_of_week,
            ),
            "args": (name,),
        }

    return schedule
