"""Skill CLI generator."""

from __future__ import annotations

from pathlib import Path

from hof.agent.sandbox import skill_cli


def test_script_body_contains_function_name_and_urls() -> None:
    body = skill_cli._script_body("list_expenses")
    assert "list_expenses" in body
    assert "API_BASE_URL" in body
    assert "/api/functions/" in body
    assert "API_TOKEN" in body
    assert "HOF_BASIC_PASSWORD" in body


def test_write_skill_cli_tree_with_mock_registry(monkeypatch: object, tmp_path: Path) -> None:
    class _Reg:
        functions = {"acme_test_fn": object()}

    monkeypatch.setattr(skill_cli, "registry", _Reg())
    paths = skill_cli.write_skill_cli_tree(
        tmp_path,
        names=frozenset({"acme_test_fn"}),
    )
    assert len(paths) == 1
    assert (tmp_path / "acme-test-fn").exists()
    assert "acme_test_fn" in paths[0].read_text(encoding="utf-8")
