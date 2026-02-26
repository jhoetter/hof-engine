from hof import Table, Column, ForeignKey, types


class Lead(Table):
    """A sales lead to be researched and enriched."""

    name = Column(types.String, required=True)
    email = Column(types.String, nullable=True, index=True)
    company = Column(types.String, nullable=True, index=True)
    title = Column(types.String, nullable=True)
    source = Column(types.String, nullable=True)
    status = Column(
        types.Enum("new", "enriching", "enriched", "reviewed", "rejected"),
        default="new",
        index=True,
    )
    raw_data = Column(types.JSON, default={})


class EnrichmentResult(Table):
    """Structured data extracted by LLM enrichment for a lead."""

    lead_id = ForeignKey(Lead, on_delete="CASCADE")
    company_description = Column(types.Text, nullable=True)
    industry = Column(types.String, nullable=True)
    company_size = Column(types.String, nullable=True)
    linkedin_url = Column(types.String_(1024), nullable=True)
    recent_news = Column(types.JSON, default=[])
    confidence_score = Column(types.Float, nullable=True)
    enriched_by = Column(types.String, nullable=True)
