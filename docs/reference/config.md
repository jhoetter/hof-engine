# Configuration

Every hof project has a `hof.config.py` at the project root. This file defines all project settings.

## Basic Configuration

```python
from hof import Config

config = Config(
    app_name="my-app",
    database_url="postgresql://localhost:5432/myapp",
    redis_url="redis://localhost:6379/0",
)
```

## Full Configuration Reference

```python
from hof import Config

config = Config(
    # Application
    app_name="my-app",                          # Required. Used in admin UI, logs, etc.
    debug=False,                                # Enable debug mode (verbose logging, auto-reload)
    secret_key="${HOF_SECRET_KEY}",              # Secret key for signing tokens

    # Database
    database_url="postgresql://localhost:5432/myapp",  # Required. PostgreSQL connection URL
    database_pool_size=10,                             # Connection pool size (default: 10)
    database_echo=False,                               # Log SQL queries (default: False)

    # Redis / Task Queue
    redis_url="redis://localhost:6379/0",       # Required. Redis URL for Celery
    celery_concurrency=4,                       # Number of parallel worker processes (default: 4)

    # Server
    host="0.0.0.0",                             # Bind host (default: 0.0.0.0)
    port=8000,                                  # Bind port (default: 8000)
    cors_origins=["*"],                         # Allowed CORS origins

    # Authentication
    admin_username="admin",                     # Admin UI username
    admin_password="${HOF_ADMIN_PASSWORD}",      # Admin UI password
    api_key="${HOF_API_KEY}",                    # API key for programmatic access

    # LLM
    llm_provider="openai",                      # LLM provider name or instance
    llm_model="gpt-5",                          # Default model
    llm_api_key="${OPENAI_API_KEY}",             # API key (reads from env var)

    # Langfuse (optional)
    langfuse_public_key="${LANGFUSE_PUBLIC_KEY}",
    langfuse_secret_key="${LANGFUSE_SECRET_KEY}",
    langfuse_host="https://cloud.langfuse.com",

    # File Storage
    file_storage_path="./storage",              # Local file storage directory
    file_max_size_mb=100,                       # Max upload size in MB (default: 100)

    # Auto-discovery
    tables_dir="tables",                        # Directory to scan for tables (default: "tables")
    functions_dir="functions",                  # Directory to scan for functions (default: "functions")
    flows_dir="flows",                          # Directory to scan for flows (default: "flows")
    cron_dir="cron",                            # Directory to scan for cron jobs (default: "cron")
    ui_dir="ui",                                # Directory for React components (default: "ui")
)
```

## Environment Variables

Use `${VAR_NAME}` syntax to reference environment variables. hof automatically loads `.env` files from the project root.

```python
config = Config(
    database_url="${DATABASE_URL}",
    llm_api_key="${OPENAI_API_KEY}",
)
```

`.env` file:

```
DATABASE_URL=postgresql://localhost:5432/myapp
OPENAI_API_KEY=sk-...
HOF_ADMIN_PASSWORD=changeme
```

## Multiple Environments

Use Python logic for environment-specific config:

```python
import os
from hof import Config

env = os.getenv("HOF_ENV", "development")

config = Config(
    app_name="my-app",
    debug=env == "development",
    database_url=(
        "postgresql://localhost:5432/myapp"
        if env == "development"
        else "${DATABASE_URL}"
    ),
    redis_url="${REDIS_URL}" if env == "production" else "redis://localhost:6379/0",
)
```
