from datetime import datetime, timedelta, timezone

from hof import cron
from tables.lead import Lead


@cron("0 3 * * 0", timezone="UTC")
def re_enrich_stale_leads():
    """Re-enrich leads whose enrichment is older than 30 days.

    Runs weekly on Sunday at 3 AM UTC. Finds all leads with status "enriched"
    that were last updated more than 30 days ago and resets them to "new" so
    the enrichment flow picks them up again.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    stale = Lead.query(filters={"status": "enriched"}, limit=500)
    reset_count = 0

    for lead in stale:
        if lead.updated_at and lead.updated_at < cutoff:
            Lead.update(lead.id, status="new")
            reset_count += 1

    return {"reset_count": reset_count}
