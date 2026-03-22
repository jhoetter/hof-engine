"""Tests for hof.cli.result_render."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from hof.cli.result_render import render_function_result


def _capture(fmt: str, value: object) -> str:
    buf = StringIO()
    con = Console(file=buf, width=200, color_system=None, legacy_windows=False)
    render_function_result(value, fmt=fmt, console=con)
    return buf.getvalue()


def test_render_json_primitive():
    out = _capture("json", 42)
    data = json.loads(out.strip())
    assert data == 42


def test_render_auto_flat_dict_kv_table():
    out = _capture("auto", {"a": 1, "b": "two"})
    assert "a" in out and "1" in out
    assert "b" in out and "two" in out


def test_render_auto_rows_and_total():
    value = {"rows": [{"id": 1, "name": "x"}, {"id": 2, "name": "y"}], "total": 99}
    out = _capture("auto", value)
    assert "id" in out and "name" in out
    assert "x" in out and "y" in out
    assert "total" in out.lower() and "99" in out


def test_render_auto_empty_rows():
    out = _capture("auto", {"rows": [], "total": 0})
    assert "empty" in out.lower()
    assert "0" in out


def test_render_auto_list_of_dicts():
    out = _capture("auto", [{"k": "v1"}, {"k": "v2"}])
    assert "k" in out
    assert "v1" in out and "v2" in out


def test_render_auto_primitive():
    out = _capture("auto", "plain")
    assert "plain" in out


def test_render_auto_rows_mixed_types_falls_back_to_kv():
    """Non-dict rows: do not treat as tabular; whole dict is key/value."""
    value = {"rows": [{"ok": 1}, "bad"], "total": 1}
    out = _capture("auto", value)
    assert "rows" in out


@pytest.mark.parametrize("fmt", ["auto", "json"])
def test_render_no_crash_nested_value(fmt: str):
    nested = {"rows": [{"d": {"x": 1}}], "total": None}
    out = _capture(fmt, nested)
    assert len(out) > 0


def test_render_auto_rows_column_subset_notice():
    rows = [{"a": 1, "b": 2, "c": 3, "d": 4}]
    buf = StringIO()
    con = Console(file=buf, width=200, color_system=None, legacy_windows=False)
    render_function_result(
        {"rows": rows, "total": 1},
        fmt="auto",
        console=con,
        max_columns=2,
        wrap_cells=True,
    )
    out = buf.getvalue()
    assert "Showing 2 of 4 columns" in out
    assert "1" in out


def test_render_wrap_cells_long_description():
    long = "Monthly SaaS subscription – Acme Corp extended description text"
    buf = StringIO()
    con = Console(file=buf, width=72, color_system=None, legacy_windows=False)
    render_function_result(
        {"rows": [{"description": long, "amount": 8500}], "total": 1},
        fmt="auto",
        console=con,
        max_columns=3,
        max_cell=500,
        wrap_cells=True,
    )
    out = buf.getvalue()
    assert "Monthly SaaS" in out
    assert "8500" in out
