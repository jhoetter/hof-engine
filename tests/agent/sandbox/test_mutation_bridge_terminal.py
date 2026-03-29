"""Tests for sandbox terminal mutation detection (skip duplicate mutation in one round)."""

from __future__ import annotations

import pytest

from hof.agent.sandbox.mutation_bridge import (
    parse_terminal_exec_command,
    terminal_exec_command_targets_mutation,
)


def test_parse_terminal_exec_command() -> None:
    assert (
        parse_terminal_exec_command('{"command":"hof fn list_expenses {}"}')
        == "hof fn list_expenses {}"
    )
    assert parse_terminal_exec_command("{}") == ""


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("hof fn create_expense '{}'", True),
        ("echo x; hof fn update_expense '{}'", True),
        ('curl -X POST "$API_BASE_URL/api/functions/create_expense"', True),
        ("hof fn list_expenses '{}'", False),
        ("hof fn list", False),
        ("hof fn describe create_expense", False),
        ("hof fn help", False),
        ("curl $API_BASE_URL/api/functions/list_expenses/schema", False),
        ("", False),
    ],
)
def test_terminal_exec_command_targets_mutation(
    cmd: str,
    expected: bool,
) -> None:
    ml = frozenset({"create_expense", "update_expense"})
    assert terminal_exec_command_targets_mutation(cmd, ml) is expected
