# CLI Reference

The `hof` CLI provides access to all framework features from the terminal.

## Global Options

```bash
hof --help              # Show help
hof --version           # Show version
hof --project /path     # Specify project directory (default: current directory)
```

## hof dev

Start the development server.

```bash
hof dev                         # Start all services
hof dev --port 3000             # Custom port
hof dev --no-worker             # Skip Celery worker (no flow execution)
hof dev --no-ui                 # Skip Vite dev server (API only)
hof dev --reload                # Auto-reload on file changes (default in dev)
```

Starts:
- FastAPI server (API + admin UI)
- Vite dev server (React hot reload)
- Celery worker (flow execution)

## hof flow

Manage and run flows.

```bash
# Run a flow
hof flow run <flow_name> --input '{"key": "value"}'

# List executions
hof flow list <flow_name>
hof flow list <flow_name> --status running
hof flow list <flow_name> --since 2024-01-01
hof flow list --all                              # All flows

# Get execution details
hof flow get <execution_id>
hof flow get <execution_id> --nodes              # Show per-node details
hof flow get <execution_id> --logs               # Show execution logs

# Control executions
hof flow cancel <execution_id>
hof flow retry <execution_id>

# List registered flows
hof flow list-definitions
```

## hof fn

Call and manage functions.

```bash
# Call a function
hof fn <function_name> --arg1=value1 --arg2=value2
hof fn <function_name> --json '{"arg1": "value1"}'

# List functions
hof fn list

# Show function schema
hof fn schema <function_name>
```

## hof table

Interact with tables.

```bash
# List records
hof table <table_name> list
hof table <table_name> list --filter status=pending
hof table <table_name> list --order-by -created_at
hof table <table_name> list --limit 10 --offset 20

# Get a record
hof table <table_name> get <id>

# Create a record
hof table <table_name> create --field1=value1 --field2=value2
hof table <table_name> create --json '{"field1": "value1"}'

# Update a record
hof table <table_name> update <id> --field1=new_value

# Delete a record
hof table <table_name> delete <id>

# Count records
hof table <table_name> count
hof table <table_name> count --filter status=pending

# List registered tables
hof table list-definitions
```

## hof db

Database migration commands.

```bash
hof db migrate              # Generate and apply pending migrations
hof db migrate --dry-run    # Show SQL without applying
hof db rollback             # Rollback the last migration
hof db rollback --steps 3   # Rollback multiple migrations
hof db history              # Show migration history
hof db current              # Show current migration state
```

## hof cron

Manage cron jobs.

```bash
hof cron list                       # List all cron jobs
hof cron run <cron_name>            # Manually trigger a cron job
hof cron enable <cron_name>         # Enable a cron job
hof cron disable <cron_name>        # Disable a cron job
```

## hof new

Scaffold new components.

```bash
hof new project <name>      # Create a new hof project
hof new table <name>        # Scaffold a new table
hof new function <name>     # Scaffold a new function
hof new flow <name>         # Scaffold a new flow
hof new cron <name>         # Scaffold a new cron job
hof new component <name>    # Scaffold a new React component
hof new page <name>         # Scaffold a new React page
```

## hof add

Install modules or templates from the hof-components registry.

```bash
# List all available modules and templates
hof add --list

# Install one module into current project
hof add tasks

# Install a template
hof add --template business-app

# Overwrite existing files when installing
hof add tasks --force
```

Artifact source resolution order:
- `HOF_COMPONENTS_URL` environment variable (manual override)
- `hof-engine` components manifest (`hof/components-manifest.json`) exact match by installed `hof-engine` version
- same major/minor compatible artifact from manifest (latest patch)
