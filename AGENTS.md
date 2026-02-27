# AGENTS.md — hof-engine

## What this repo is

hof-engine is the **core framework** for building full-stack Python + React applications. It is distributed as a pip package (`pip install hof-engine`) and provides:

- **Tables** — database schemas as Python classes with auto-generated CRUD APIs
- **Functions** — backend operations exposed as API endpoints and CLI commands
- **Flows** — workflow DAGs with parallel execution, LLM nodes, and human-in-the-loop
- **Cron** — scheduled tasks via Celery Beat
- **Admin UI** — React dashboard (flow viewer, table browser, pending actions)
- **CLI** — `hof` command for dev server, migrations, scaffolding, module management
- **LLM integration** — `@prompt()` decorator with structured outputs via llm-markdown
- **React hooks** — `@hof-engine/react` npm package (`hof-react/` directory)

## What does NOT belong here

- **Customer-specific business logic** — belongs in the customer repo
- **Reusable modules** (tables, flows, functions, UI for specific use cases like lead enrichment, billing) — belongs in **hof-components**
- **Deployment, server provisioning, DNS, infrastructure** — belongs in **hof-os**
- **Design tokens, brand colors, Tailwind themes** — belongs in **design-system-\<customer\>** repos (managed by hof-os)
- **Application examples** — belong in **hof-components** (as modules or in `docs/examples/`)

## Ecosystem

This repo is part of the bithof platform (hof-os, hof-engine, hof-components, design-system-\<customer\>, customer-\<name\>). For the full ecosystem map, repo boundaries, and ownership rules, see:

```
~/repos/hof-os/docs/ecosystem.md
```

## Repo Structure

```
hof-engine/
├── hof/                    # Main Python package (this ships in the pip wheel)
│   ├── api/                # FastAPI server, routes, auth
│   ├── cli/                # CLI commands (dev, db, flow, fn, table, cron, new, add)
│   ├── core/               # Registry, discovery
│   ├── db/                 # SQLAlchemy engine, migrations
│   ├── flows/              # Flow execution engine
│   ├── llm/                # LLM decorators and integration
│   └── ui/
│       ├── admin/          # Admin React UI (pre-built to dist/ for pip wheel)
│       └── vite.py         # ViteManager for user React components
├── hof-react/              # @hof-engine/react npm package (hooks for customer UIs)
├── docs/                   # Framework reference documentation
│   ├── guide/              # Getting started
│   └── reference/          # Tables, functions, flows, UI, CLI, config, LLM
├── tests/                  # pytest test suite
├── hatch_build.py          # Hatch hook: compiles admin UI before wheel build
├── pyproject.toml          # Package config, dependencies, build settings
└── .github/workflows/      # CI + PyPI publish
```

## Rules for AI agents

1. **Framework only.** Every change here should benefit ALL customer projects, not just one. If it's specific to a use case, it belongs in hof-components.

2. **The pip wheel must be self-contained.** The admin UI ships as pre-built static assets (`hof/ui/admin/dist/`). Never add runtime dependencies on Node.js, hof-components, or hof-os.

3. **The `hof add` CLI fetches from hof-components.** If you're adding a new module, add it to hof-components, not here. The `hof/cli/commands/add.py` command handles the copy.

4. **`hof-react/` is a separate npm package.** It has its own `package.json`, `tsconfig.json`, and build step (`tsup`). Changes to React hooks go here, not in `hof/ui/admin/`.

5. **Docs in this repo are framework reference only.** Application examples and tutorials belong in hof-components (`docs/examples/`).
