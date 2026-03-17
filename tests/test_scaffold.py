"""Tests for the project scaffolding API (get_project_files)."""

from hof.scaffold import get_project_files


def test_returns_dict_of_strings():
    files = get_project_files("My App")
    assert isinstance(files, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in files.items())


def test_core_files_present():
    files = get_project_files("test-project")
    expected = [
        "hof.config.py",
        "pyproject.toml",
        "Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        "pyrightconfig.json",
        ".env",
    ]
    for path in expected:
        assert path in files, f"Missing expected file: {path}"


def test_directory_init_files():
    files = get_project_files("test-project")
    for dirname in ("tables", "functions", "flows", "cron"):
        assert f"{dirname}/__init__.py" in files


def test_ui_gitkeep_files():
    files = get_project_files("test-project")
    assert "ui/components/.gitkeep" in files
    assert "ui/pages/.gitkeep" in files


def test_name_interpolation():
    files = get_project_files("acme portal")
    assert 'app_name="acme portal"' in files["hof.config.py"]


def test_no_index_page_in_scaffold():
    """Scaffold must NOT create ui/pages/index.tsx — templates provide it."""
    files = get_project_files("test-project")
    assert "ui/pages/index.tsx" not in files


def test_slug_derived_from_name():
    files = get_project_files("Acme Portal")
    assert 'name = "acme-portal"' in files["pyproject.toml"]
    assert "DB_NAME=app" in files[".env"]


def test_explicit_slug_overrides_derived():
    files = get_project_files("My Cool App", slug="cool-app")
    assert 'name = "cool-app"' in files["pyproject.toml"]
    assert "DB_NAME=app" in files[".env"]
    assert 'app_name="My Cool App"' in files["hof.config.py"]


def test_dockerfile_uses_github_token():
    files = get_project_files("test-project")
    assert "GITHUB_TOKEN" in files["Dockerfile"]
    assert "hof-engine" in files["Dockerfile"]


def test_dockerfile_cmd_uses_uvicorn():
    files = get_project_files("test-project")
    assert "uvicorn" in files["Dockerfile"]
    assert "hof dev" not in files["Dockerfile"]


def test_dockerfile_cmd_includes_ensure_db():
    files = get_project_files("test-project")
    assert "hof.db.ensure_db" in files["Dockerfile"]


def test_compose_has_no_app_service():
    files = get_project_files("test-project")
    compose = files["docker-compose.yml"]
    assert "app:" not in compose
    assert "db:" in compose
    assert "redis:" in compose


def test_compose_local_dev_comment():
    files = get_project_files("test-project")
    assert "Local development" in files["docker-compose.yml"]
    assert "hof dev" in files["docker-compose.yml"]


def test_slug_with_special_characters():
    files = get_project_files("Über Cool App!!")
    pyproject = files["pyproject.toml"]
    name_line = pyproject.split("\n")[1]
    name_value = name_line.split('"')[1]
    assert name_value.isascii()
    assert all(c.isalnum() or c == "-" for c in name_value)
