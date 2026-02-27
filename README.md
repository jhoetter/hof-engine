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
