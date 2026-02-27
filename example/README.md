# hof-engine Example: Lead Enrichment CRM

This is the reference example project for [hof-engine](https://github.com/jhoetter/hof-engine). It demonstrates a CRM with AI-powered lead enrichment and human-in-the-loop review.

---

## Quick Start

```bash
cp .env.example .env   # fill in DATABASE_URL, REDIS_URL, OPENAI_API_KEY
hof db migrate
hof dev
```

Then open [http://localhost:8000/admin](http://localhost:8000/admin).

---

## Common Commands

```bash
# Import leads from JSON
hof fn import_leads --json '{"leads_json": "[{\"name\": \"Alice\", \"company\": \"Acme\"}]"}'

# Enrich all new leads
hof fn trigger_bulk_enrichment

# Enrich a single lead
hof fn trigger_enrichment --json '{"lead_id": "<uuid>"}'

# Check flow executions
hof flow list enrich_lead
```

---

## How the Whole System Works

### The Three Repos

```
hof-engine          → the framework you maintain (pip package)
hof-components      → a library of reusable modules (copy-paste registry)
customer-<name>     → one repo per customer (self-contained app)
```

### Starting a New Customer Project

```bash
# 1. Create a new repo on GitHub (e.g. customer-newclient), clone it
cd ~/repos
git clone git@github.com:jhoetter/customer-newclient.git
cd customer-newclient

# 2. Scaffold the project
hof new project newclient

# 3. Add modules from hof-components
hof add lead-enrichment
# → copies tables/lead.py, flows/enrich_lead.py, ui/pages/leads.tsx, etc.
# → appends OPENAI_API_KEY= to .env
# → prints post-install notes

# 4. Fill in .env, then start developing
hof db migrate
hof dev
```

The files are now **owned by the customer repo** — edit them freely for that specific customer.

### Adding a New Reusable Module to hof-components

When you build something for one customer that you want to reuse:

```bash
cd ~/repos/hof-components

# Create the module structure
mkdir -p modules/stripe-billing/{tables,functions,flows,ui/components,ui/pages}

# Write the files + module.json, add entry to registry.json
git add . && git commit -m "Add stripe-billing module" && git push
```

Next time any customer needs it: `hof add stripe-billing`.

### Updating the Framework (hof-engine)

```bash
cd ~/repos/hof-engine

# Make changes, bump version in pyproject.toml
# Create a GitHub release → triggers .github/workflows/publish.yml
# → compiles admin UI → builds wheel → publishes to PyPI
```

Customers update by bumping `hof-engine>=0.1.1` in their `pyproject.toml`.

### Deploying a Customer Project

```bash
git push origin main
# → triggers .github/workflows/deploy.yml
# → SSH into Hetzner server
# → git pull + docker compose up --build + hof db migrate
```

One-time setup: add `HETZNER_HOST`, `HETZNER_USER`, `HETZNER_SSH_KEY` as GitHub repo secrets.

### The Key Mental Model

`hof add` works like `npx shadcn add` — it **copies** code into your project. After that, the files are yours. There is no runtime link back to `hof-components`. The only runtime dependency is `hof-engine` (the pip package).

```
hof-components  →  hof add lead-enrichment  →  customer/tables/lead.py
                                                (now owned by the customer project)
```

- Customize any module file per customer without affecting others
- Customers can take their repo and run it independently with just `pip install hof-engine`
- To propagate a bug fix from `hof-components` to existing customers, copy the fix manually (a future `hof add --diff` will show what changed)
