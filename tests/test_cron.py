"""Tests for hof.cron.scheduler."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from hof.core.registry import registry
from hof.cron.scheduler import CronMetadata, cron, get_celery_beat_schedule


class TestCronDecorator:
    def test_registers_in_registry(self):
        @cron("0 2 * * *")
        def daily_job() -> None:
            pass

        assert registry.get_cron("daily_job") is not None

    def test_metadata_schedule(self):
        @cron("*/15 * * * *")
        def frequent_job() -> None:
            pass

        meta = registry.get_cron("frequent_job")
        assert meta.schedule == "*/15 * * * *"

    def test_metadata_defaults(self):
        @cron("0 0 * * *")
        def default_job() -> None:
            pass

        meta = registry.get_cron("default_job")
        assert meta.timezone == "UTC"
        assert meta.retries == 0
        assert meta.timeout == 300
        assert meta.enabled is True

    def test_metadata_custom_options(self):
        @cron("0 6 * * 1", timezone="Europe/Berlin", retries=2, timeout=60, enabled=False)
        def custom_job() -> None:
            pass

        meta = registry.get_cron("custom_job")
        assert meta.timezone == "Europe/Berlin"
        assert meta.retries == 2
        assert meta.timeout == 60
        assert meta.enabled is False

    def test_function_still_callable(self):
        results = []

        @cron("0 * * * *")
        def callable_job() -> None:
            results.append(1)

        callable_job()
        assert results == [1]

    def test_hof_cron_attribute(self):
        @cron("0 0 * * *")
        def attr_job() -> None:
            pass

        assert hasattr(attr_job, "_hof_cron")
        assert isinstance(attr_job._hof_cron, CronMetadata)

    def test_name_from_function(self):
        @cron("0 0 * * *")
        def named_job() -> None:
            pass

        meta = registry.get_cron("named_job")
        assert meta.name == "named_job"


class TestCronMetadataToDict:
    def test_to_dict_structure(self):
        @cron("0 3 * * 0", timezone="UTC", retries=1, timeout=120, enabled=True)
        def dict_job() -> None:
            pass

        meta = registry.get_cron("dict_job")
        d = meta.to_dict()
        assert d["name"] == "dict_job"
        assert d["schedule"] == "0 3 * * 0"
        assert d["timezone"] == "UTC"
        assert d["retries"] == 1
        assert d["timeout"] == 120
        assert d["enabled"] is True

    def test_to_dict_does_not_include_fn(self):
        @cron("0 0 * * *")
        def fn_job() -> None:
            pass

        meta = registry.get_cron("fn_job")
        d = meta.to_dict()
        assert "fn" not in d


class TestGetCeleryBeatSchedule:
    def test_returns_dict(self):
        @cron("0 0 * * *")
        def sched_job() -> None:
            pass

        mock_crontab = MagicMock()
        with patch("celery.schedules.crontab", mock_crontab):
            schedule = get_celery_beat_schedule()

        assert isinstance(schedule, dict)

    def test_enabled_jobs_included(self):
        @cron("0 1 * * *", enabled=True)
        def enabled_job() -> None:
            pass

        mock_crontab = MagicMock()
        with patch("celery.schedules.crontab", mock_crontab):
            schedule = get_celery_beat_schedule()

        assert "hof-cron-enabled_job" in schedule

    def test_disabled_jobs_excluded(self):
        @cron("0 1 * * *", enabled=False)
        def disabled_job() -> None:
            pass

        mock_crontab = MagicMock()
        with patch("celery.schedules.crontab", mock_crontab):
            schedule = get_celery_beat_schedule()

        assert "hof-cron-disabled_job" not in schedule

    def test_invalid_schedule_skipped(self):
        meta = CronMetadata(
            name="bad_schedule",
            schedule="not a valid cron",
            fn=lambda: None,
        )
        registry.register_cron(meta)

        mock_crontab = MagicMock()
        with patch("celery.schedules.crontab", mock_crontab):
            schedule = get_celery_beat_schedule()

        assert "hof-cron-bad_schedule" not in schedule

    def test_schedule_entry_structure(self):
        @cron("30 8 * * 1-5")
        def weekday_job() -> None:
            pass

        mock_crontab = MagicMock(return_value="mock_schedule")
        with patch("celery.schedules.crontab", mock_crontab):
            schedule = get_celery_beat_schedule()

        entry = schedule["hof-cron-weekday_job"]
        assert entry["task"] == "hof.execute_cron"
        assert entry["args"] == ("weekday_job",)
        assert "schedule" in entry

    def test_crontab_called_with_correct_parts(self):
        @cron("5 10 15 3 2")
        def specific_job() -> None:
            pass

        mock_crontab = MagicMock(return_value="mock_schedule")
        with patch("celery.schedules.crontab", mock_crontab):
            get_celery_beat_schedule()

        mock_crontab.assert_called_with(
            minute="5",
            hour="10",
            day_of_month="15",
            month_of_year="3",
            day_of_week="2",
        )
