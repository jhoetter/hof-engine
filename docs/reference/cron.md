# Cron Jobs

Cron jobs are scheduled tasks that run on a recurring schedule. They use Celery Beat under the hood.

## Defining a Cron Job

```python
# cron/daily_cleanup.py
from hof import cron

@cron("0 2 * * *")  # Every day at 2 AM UTC
def cleanup_stale_documents():
    """Remove documents older than 90 days."""
    from tables.document import Document
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=90)
    Document.bulk_delete(filters={"created_at__lt": cutoff})
```

## Cron Schedule Syntax

Standard cron expression: `minute hour day_of_month month day_of_week`

| Expression | Description |
|-----------|-------------|
| `* * * * *` | Every minute |
| `0 * * * *` | Every hour |
| `0 2 * * *` | Daily at 2:00 AM |
| `0 0 * * 0` | Weekly on Sunday at midnight |
| `0 0 1 * *` | Monthly on the 1st at midnight |
| `*/15 * * * *` | Every 15 minutes |

## Cron Options

```python
@cron(
    "0 2 * * *",
    timezone="Europe/Berlin",   # Timezone (default: UTC)
    retries=3,                  # Retry on failure
    timeout=600,                # Max execution time in seconds
    enabled=True,               # Can be disabled without removing
)
def my_scheduled_task():
    ...
```

## CLI

```bash
hof cron list                   # List all registered cron jobs
hof cron run daily_cleanup      # Manually trigger a cron job
hof cron enable daily_cleanup   # Enable a disabled cron job
hof cron disable daily_cleanup  # Disable a cron job
```

## Monitoring

Cron executions are logged in the database and visible in the admin UI under the "Cron" section. Each execution records:

- Start time, end time, duration
- Status (success / failed)
- Output or error message
- Retry attempts
