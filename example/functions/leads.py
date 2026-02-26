import json

from hof import function, HofError
from tables.lead import Lead


@function(tags=["leads"])
def import_leads(leads_json: str) -> dict:
    """Bulk-import leads from a JSON string.

    Expects a JSON array of objects with at least a "name" field:
    [{"name": "Alice", "email": "alice@acme.com", "company": "Acme Inc"}, ...]
    """
    try:
        records = json.loads(leads_json)
    except json.JSONDecodeError as exc:
        raise HofError(f"Invalid JSON: {exc}", status_code=400)

    if not isinstance(records, list):
        raise HofError("Expected a JSON array of lead objects", status_code=400)

    created = Lead.bulk_create(
        [
            {
                "name": r["name"],
                "email": r.get("email"),
                "company": r.get("company"),
                "title": r.get("title"),
                "source": r.get("source", "manual_import"),
                "status": "new",
                "raw_data": r,
            }
            for r in records
        ]
    )
    return {"imported": len(created)}


@function(tags=["leads", "enrichment"])
def trigger_enrichment(lead_id: str) -> dict:
    """Trigger the enrichment workflow for a single lead."""
    lead = Lead.get(lead_id)
    if lead is None:
        raise HofError(f"Lead {lead_id} not found", status_code=404)

    Lead.update(lead_id, status="enriching")

    from flows.enrich_lead import enrich_lead_flow

    execution = enrich_lead_flow.run(lead_id=str(lead_id))
    return {"execution_id": execution.id, "lead_id": str(lead_id)}


@function(tags=["leads", "enrichment"])
def trigger_bulk_enrichment(filter_status: str = "new") -> dict:
    """Trigger enrichment for all leads matching a status."""
    leads = Lead.query(filters={"status": filter_status}, limit=500)
    executions = []

    from flows.enrich_lead import enrich_lead_flow

    for lead in leads:
        Lead.update(lead.id, status="enriching")
        execution = enrich_lead_flow.run(lead_id=str(lead.id))
        executions.append({"lead_id": str(lead.id), "execution_id": execution.id})

    return {"triggered": len(executions), "executions": executions}
