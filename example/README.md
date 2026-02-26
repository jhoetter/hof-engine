hof db migrate
hof dev
hof fn import_leads --json '{"leads_json": "[{\"name\": \"Alice\", \"company\": \"Acme\"}]"}'
hof fn trigger_bulk_enrichment
hof flow list enrich_lead
