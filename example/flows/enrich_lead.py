from pydantic import BaseModel

from hof import Flow, human_node, HofError
from hof.llm import llm
from tables.lead import Lead, EnrichmentResult


# -- Structured output model for the LLM enrichment step ---------------------

class LeadEnrichment(BaseModel):
    company_description: str
    industry: str
    company_size: str
    linkedin_url: str | None = None
    recent_news: list[str] = []
    confidence_score: float


# -- Flow definition ---------------------------------------------------------

enrich_lead_flow = Flow("enrich_lead")


@enrich_lead_flow.node
def fetch_lead(lead_id: str) -> dict:
    """Load the lead from the database and validate it has enough data."""
    lead = Lead.get(lead_id)
    if lead is None:
        raise HofError(f"Lead {lead_id} not found", status_code=404)

    lead_data = lead.to_dict()

    if not lead_data.get("name"):
        raise HofError("Lead has no name — cannot research", status_code=400)

    return {
        "lead_id": str(lead_data["id"]),
        "name": lead_data["name"],
        "email": lead_data.get("email") or "",
        "company": lead_data.get("company") or "",
        "title": lead_data.get("title") or "",
    }


@enrich_lead_flow.node(depends_on=[fetch_lead])
def research_online(lead_id: str, name: str, email: str, company: str, title: str) -> dict:
    """Compile a research dossier from available lead data.

    In production you would call a search API (Serper, Tavily, etc.) here.
    This example builds a structured research prompt from what we already know
    so the LLM can infer and extrapolate.
    """
    fragments: list[str] = []

    fragments.append(f"Person: {name}")
    if title:
        fragments.append(f"Job title: {title}")
    if company:
        fragments.append(f"Company: {company}")
    if email:
        domain = email.split("@")[-1] if "@" in email else ""
        if domain and domain not in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com"):
            fragments.append(f"Corporate domain: {domain}")

    research_summary = "\n".join(fragments)

    return {
        "lead_id": lead_id,
        "name": name,
        "company": company,
        "research_summary": research_summary,
    }


@enrich_lead_flow.node(depends_on=[research_online])
@llm(reasoning_first=True)
def enrich_with_llm(lead_id: str, name: str, company: str, research_summary: str) -> LeadEnrichment:
    """You are a B2B sales intelligence analyst.

Given the following research about a lead, extract structured enrichment data.
Be as specific as possible. If you cannot determine a field with confidence,
make your best educated guess and reflect that in the confidence_score (0.0-1.0).

Research:
{research_summary}

Return the enrichment data as structured output."""


@enrich_lead_flow.node(depends_on=[enrich_with_llm])
@human_node(ui="LeadReview", timeout="72h")
def review_enrichment(
    lead_id: str,
    name: str,
    company: str,
    company_description: str,
    industry: str,
    company_size: str,
    linkedin_url: str | None,
    recent_news: list[str],
    confidence_score: float,
    **kwargs,
) -> dict:
    """Human reviews the LLM-enriched data before it is persisted.

    The LeadReview React component is rendered in the admin UI.
    The reviewer can approve, edit fields, or reject the enrichment.
    """
    pass  # Framework renders the UI and waits for human input


@enrich_lead_flow.node(depends_on=[review_enrichment])
def store_enrichment(
    lead_id: str,
    approved: bool,
    company_description: str = "",
    industry: str = "",
    company_size: str = "",
    linkedin_url: str | None = None,
    recent_news: list | None = None,
    confidence_score: float = 0.0,
    **kwargs,
) -> dict:
    """Persist the approved enrichment to the database, or mark as rejected."""
    if not approved:
        Lead.update(lead_id, status="rejected")
        return {"lead_id": lead_id, "stored": False, "reason": "rejected_by_reviewer"}

    EnrichmentResult.create(
        lead_id=lead_id,
        company_description=company_description,
        industry=industry,
        company_size=company_size,
        linkedin_url=linkedin_url,
        recent_news=recent_news or [],
        confidence_score=confidence_score,
        enriched_by="gpt-4o",
    )

    Lead.update(lead_id, status="enriched")

    return {"lead_id": lead_id, "stored": True}
