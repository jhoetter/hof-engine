# Tables

Tables define your database schema as Python classes. Each `Table` subclass maps to a PostgreSQL table with auto-generated CRUD endpoints, CLI commands, and admin UI views.

## Defining a Table

```python
from hof import Table, Column, types

class Document(Table):
    name = Column(types.String, required=True)
    category = Column(types.String, nullable=True)
    file_path = Column(types.String)
    metadata = Column(types.JSON, default={})
    status = Column(types.Enum("pending", "processed", "reviewed"), default="pending")
    created_at = Column(types.DateTime, auto_now=True)
    updated_at = Column(types.DateTime, auto_now_update=True)
```

Every table automatically gets an `id` column (UUID primary key) and `created_at` / `updated_at` timestamps if not explicitly defined.

## Column Types

| Type | Python Type | PostgreSQL Type | Notes |
|------|-------------|-----------------|-------|
| `types.String` | `str` | `VARCHAR(255)` | Default max length 255 |
| `types.Text` | `str` | `TEXT` | Unlimited length |
| `types.Integer` | `int` | `INTEGER` | |
| `types.Float` | `float` | `DOUBLE PRECISION` | |
| `types.Boolean` | `bool` | `BOOLEAN` | |
| `types.DateTime` | `datetime` | `TIMESTAMP WITH TIME ZONE` | |
| `types.Date` | `date` | `DATE` | |
| `types.JSON` | `dict / list` | `JSONB` | Stored as JSONB for indexing |
| `types.Enum(...)` | `str` | `VARCHAR` with check | Validated against allowed values |
| `types.UUID` | `uuid.UUID` | `UUID` | |
| `types.File` | `str` | `VARCHAR` | Stores file path/reference |

## Column Options

```python
Column(
    type,                    # Required. One of types.*
    required=False,          # If True, NOT NULL and must be provided on create
    nullable=True,           # If True, allows NULL values
    default=None,            # Default value (static or callable)
    unique=False,            # If True, adds UNIQUE constraint
    index=False,             # If True, creates a B-tree index
    primary_key=False,       # If True, marks as primary key (overrides auto id)
    auto_now=False,          # If True, set to now() on creation
    auto_now_update=False,   # If True, set to now() on every update
)
```

## Table Class API

### CRUD Operations

```python
# Create
doc = Document.create(name="report.pdf", category="finance")

# Get by ID
doc = Document.get("uuid-here")

# Query
docs = Document.query(
    filters={"status": "pending", "category": "finance"},
    order_by="-created_at",   # Prefix with - for descending
    limit=10,
    offset=0,
)

# Update
doc = Document.update("uuid-here", status="processed")

# Delete
Document.delete("uuid-here")

# Count
count = Document.count(filters={"status": "pending"})
```

### Bulk Operations

```python
# Bulk create
docs = Document.bulk_create([
    {"name": "a.pdf", "category": "finance"},
    {"name": "b.pdf", "category": "legal"},
])

# Bulk update
Document.bulk_update(
    filters={"status": "pending"},
    values={"status": "processed"},
)

# Bulk delete
Document.bulk_delete(filters={"category": "archived"})
```

## Relationships

```python
from hof import Table, Column, types, ForeignKey

class Project(Table):
    name = Column(types.String, required=True)

class Document(Table):
    name = Column(types.String, required=True)
    project_id = ForeignKey(Project, on_delete="CASCADE")
```

Access related records:

```python
doc = Document.get("uuid")
project = doc.project          # Lazy-loaded related Project

project = Project.get("uuid")
docs = project.documents       # Reverse relation (auto-named)
```

## Auto-Generated Endpoints

Every table gets REST endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tables/{name}` | List records (with filtering, pagination) |
| `POST` | `/api/tables/{name}` | Create a record |
| `GET` | `/api/tables/{name}/{id}` | Get a single record |
| `PUT` | `/api/tables/{name}/{id}` | Update a record |
| `DELETE` | `/api/tables/{name}/{id}` | Delete a record |

Query parameters for list endpoint:

- `?filter=status:pending,category:finance` -- filter by field values
- `?order_by=-created_at` -- sort (prefix `-` for descending)
- `?limit=10&offset=0` -- pagination
- `?search=report` -- full-text search across string columns

## CLI Commands

```bash
hof table document list                          # List all documents
hof table document list --filter status=pending  # Filtered list
hof table document get <id>                      # Get by ID
hof table document create --name=report.pdf      # Create
hof table document update <id> --status=done     # Update
hof table document delete <id>                   # Delete
hof table document count                         # Count records
```

## Migrations

Tables use Alembic under the hood. When you change a table definition:

```bash
hof db migrate              # Generate and apply migration
hof db migrate --dry-run    # Show SQL without applying
hof db rollback             # Rollback last migration
hof db history              # Show migration history
```
