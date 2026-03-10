# Getting Started

This guide walks you through installing hof-engine, creating your first project, and running it.

## Prerequisites

- Python 3.11+
- Node.js 18+ (for React UI compilation)
- PostgreSQL (running locally or remotely)
- Redis (for task queue / parallel workflow execution)

## Installation

```bash
pip install hof-engine
```

This installs the `hof` CLI and the Python framework.

## Create a New Project

```bash
hof new project my-app
cd my-app
```

This scaffolds the following structure:

```
my-app/
  hof.config.py
  tables/
    __init__.py
  functions/
    __init__.py
  flows/
    __init__.py
  ui/
    components/
    pages/
  cron/
    __init__.py
```

## Configure Your Project

Edit `hof.config.py`:

```python
from hof import Config

config = Config(
    app_name="my-app",
    database_url="postgresql://localhost:5432/myapp",
    redis_url="redis://localhost:6379/0",
)
```

## Define Your First Table

Create `tables/task.py`:

```python
from hof import Table, Column, types

class Task(Table):
    title = Column(types.String, required=True)
    description = Column(types.Text, nullable=True)
    done = Column(types.Boolean, default=False)
    created_at = Column(types.DateTime, auto_now=True)
```

Run the migration:

```bash
hof db migrate
```

This generates and applies an Alembic migration for the `task` table. You now have:

- A `task` table in PostgreSQL
- CRUD API endpoints at `/api/tables/task`
- CLI access via `hof table task list`, `hof table task get <id>`
- A table browser in the admin UI

## Define Your First Function

Create `functions/greet.py`:

```python
from hof import function

@function
def greet(name: str) -> dict:
    """Return a greeting message."""
    return {"message": f"Hello, {name}!"}
```

This is now available as:

- `POST /api/functions/greet` with body `{"name": "World"}`
- `hof fn greet --name=World`

## Define Your First Flow

Create `flows/onboarding.py`:

```python
from hof import Flow
from tables.task import Task

onboarding = Flow("onboarding")

@onboarding.node
def create_welcome_task(user_name: str) -> dict:
    """Create a welcome task for a new user."""
    task = Task.create(
        title=f"Welcome {user_name}",
        description="Complete your profile to get started.",
    )
    return {"task_id": task.id}

@onboarding.node(depends_on=[create_welcome_task])
def send_notification(task_id: str) -> dict:
    """Send a notification about the new task."""
    # In a real app, this would send an email or push notification.
    return {"notified": True, "task_id": task_id}
```

Run it:

```bash
hof flow run onboarding --input '{"user_name": "Alice"}'
```

## Start the Dev Server

```bash
hof dev
```

This starts:

1. **FastAPI server** on `http://localhost:8000` (API + admin UI)
2. **Vite dev server** for hot-reloading React components
3. **Celery worker** for parallel flow execution

Open `http://localhost:8000/admin` to see the admin dashboard with your tables, functions, and flows.

## Next Steps

- [API Reference](../reference/tables.md) -- full documentation for all decorators and classes
- [Example Project](../examples/document-processing.md) -- a complete document processing pipeline
- [Flows Guide](../reference/flows.md) -- advanced flow patterns including human-in-the-loop
- [UI Guide](../reference/ui.md) -- building React interfaces that integrate with flows
