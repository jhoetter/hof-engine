# hof-engine

Full-stack Python + React framework for building applications with workflows, database tables, UIs, and LLM integration -- all defined as code.

## Features

- **Tables**: Define database schemas as Python classes with auto-generated CRUD APIs
- **Functions**: Backend operations exposed as API endpoints and CLI commands
- **Flows**: Workflow DAGs with parallel execution, LLM nodes, and human-in-the-loop
- **UIs**: Native React components with hot reload via Vite
- **Cron Jobs**: Scheduled tasks with Celery Beat
- **CLI**: Full CLI access to all features
- **Admin Dashboard**: Visual flow viewer, table browser, execution history, and logs
- **LLM Integration**: First-class support via llm-markdown with structured outputs
- **Self-Contained Docs**: Bundle Markdown documentation with your app, served and rendered in the admin UI

## Quick Start

```bash
pip install hof-engine
hof new project my-app
cd my-app
```

Define a table:

```python
# tables/task.py
from hof import Table, Column, types

class Task(Table):
    title = Column(types.String, required=True)
    done = Column(types.Boolean, default=False)
```

Define a function:

```python
# functions/greet.py
from hof import function

@function
def greet(name: str) -> dict:
    return {"message": f"Hello, {name}!"}
```

Define a flow:

```python
# flows/onboarding.py
from hof import Flow

onboarding = Flow("onboarding")

@onboarding.node
def create_task(user_name: str) -> dict:
    return {"task": f"Welcome {user_name}"}

@onboarding.node(depends_on=[create_task])
def notify(task: str) -> dict:
    return {"notified": True}
```

Run:

```bash
hof db migrate
hof dev
```

**`hof fn` output:** By default, `hof fn <name>` prints human-friendly tables (for list-like results such as `{ "rows", "total" }`) or a key/value layout for plain dicts. Use `--format json` when you need machine-readable JSON for scripts or pipes. The `-j` / `--json` flag supplies **input** to the function only, not the output format.

## Self-Contained Docs

Every hof application can ship its own documentation. Place Markdown files in a `docs/` directory at the project root and they are automatically served at `/api/docs` and rendered in the admin UI at `/docs`.

```
my-app/
  docs/
    index.md          # Overview
    data-model.md     # Table schemas
    api.md            # Function reference
```

Use optional YAML frontmatter to control titles, section grouping, and sort order:

```markdown
---
title: Data Model
section: Reference
order: 1
---
```

No configuration needed — `docs_dir` defaults to `"docs"`. Set `docs_dir=""` in `hof.config.py` to disable. See the [Configuration reference](docs/reference/config.md#self-contained-documentation) for full details.

## Requirements

- Python 3.11+
- Node.js 18+ (for React UI)
- PostgreSQL
- Redis

## Documentation

See the [docs/](docs/) directory:

- [Getting Started](docs/guide/getting-started.md)
- [Tables Reference](docs/reference/tables.md)
- [Functions Reference](docs/reference/functions.md)
- [Flows Reference](docs/reference/flows.md)
- [UI Reference](docs/reference/ui.md)
- [LLM Reference](docs/reference/llm.md)
- [Agent Reference](docs/reference/agent.md)
- [CLI Reference](docs/reference/cli.md)
- [Configuration](docs/reference/config.md)

## Ecosystem

hof-engine is part of the bithof platform:

| Repo | Role |
|---|---|
| **hof-engine** (this repo) | Core framework (pip package) |
| [hof-components](https://github.com/jhoetter/hof-components) | Reusable modules and templates, copied via `hof add` |
| [hof-os](https://github.com/jhoetter/hof-os) | Agency operations: deployment, provisioning, billing, design system generation |
| **design-system-\<customer\>** | Per-customer design tokens + Tailwind theme (git submodule in project repos) |
| [customer-acme-test](https://github.com/jhoetter/customer-acme-test) | Example customer project |

For application examples, see [hof-components/docs/examples/](https://github.com/jhoetter/hof-components/tree/main/docs/examples).

## License

MIT

## Releasing to PyPI

This repository is configured for Trusted Publishing via GitHub Actions:

- `.github/workflows/publish.yml` for PyPI
- `.github/workflows/publish-testpypi.yml` for TestPyPI

- The repository can stay private.
- No `PYPI_TOKEN` secret is required.
- Publishing to PyPI happens when a GitHub Release is published (or manually via workflow dispatch).
- Publishing to TestPyPI is manual via workflow dispatch.

One-time setup in your PyPI account:

1. Go to [PyPI Trusted Publishers](https://pypi.org/manage/account/publishing/).
2. Add a publisher with:
   - PyPI project name: `hof-engine`
   - Owner/repo: your GitHub repo for this project
   - Workflow: `publish.yml` (filename only)
   - Environment: `pypi`
3. In GitHub, create an environment named `pypi` (recommended to require manual approval).

Optional setup for TestPyPI:

1. Go to [TestPyPI Trusted Publishers](https://test.pypi.org/manage/account/publishing/).
2. Add a publisher with:
   - TestPyPI project name: `hof-engine`
   - Owner/repo: your GitHub repo for this project
   - Workflow: `publish-testpypi.yml` (filename only)
   - Environment: `testpypi`
3. In GitHub, create an environment named `testpypi`.

Release flow:

1. Bump/update code as needed and push to default branch.
2. Create and push a git tag like `v0.1.1` (`git tag v0.1.1 && git push origin v0.1.1`).
3. The workflow builds and uploads the package to PyPI under your account/project ownership.
4. Optional: also publish a GitHub Release for changelog/visibility.

Manual publish options:

- Publish to PyPI now (no release): run the `Publish to PyPI` workflow via GitHub Actions `Run workflow`.
- Publish to TestPyPI: run the `Publish to TestPyPI` workflow via GitHub Actions `Run workflow`.
