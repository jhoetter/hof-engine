# hof-engine Distribution & Module System Roadmap

---

## Implementation Status

### Completed

- [x] **Hatch build hook** — `hatch_build.py` compiles admin UI before packaging the wheel
- [x] **pyproject.toml** — build hook registered, `hof/ui/admin/dist` force-included, `node_modules` excluded
- [x] **Admin UI `.gitignore`** — `dist/` and `node_modules/` ignored locally
- [x] **GitHub Actions publish workflow** — `.github/workflows/publish.yml` triggers on release, publishes to PyPI
- [x] **ViteManager** — generates `package.json` with `@hof-engine/react` dependency; uses local `file:` path until npm publish
- [x] **`hof add` CLI command** — full implementation with `--list`, `--template`, `--force`, `.hof/modules.json` tracking
- [x] **`hof new project` scaffold** — generates `Dockerfile`, `docker-compose.yml`, `.github/workflows/deploy.yml`, `pyproject.toml`, `pyrightconfig.json`
- [x] **hof-components repo** — `registry.json`, `lead-enrichment` module, `crm` template (https://github.com/jhoetter/hof-components)
- [x] **customer-acme-test repo** — full customer project with lead-enrichment installed, Docker deploy setup (https://github.com/jhoetter/customer-acme-test)
- [x] **`pyrightconfig.json`** — added to `hof-components`, `customer-acme-test`, and `hof new project` scaffold to suppress `hof` import errors in Cursor

### Pending Decisions

- [ ] **PyPI vs GitHub Packages** — publish workflow targets public PyPI. If you want the package private, switch to GitHub Packages and update the `--index-url`. Either way, add a `PYPI_TOKEN` secret to the hof-engine repo before the first release.

- [ ] **Publish `@hof-engine/react` to npm** — the package is built locally (`hof-react/dist/` exists) and customer UIs use a `file:` path for now. When ready: `cd hof-react && npm publish --access public`. After publishing, remove the `_hof_react_version()` fallback in `hof/ui/vite.py` and replace with the fixed `"^0.1.0"` string.

- [ ] **`pyrightconfig.json` python path is hardcoded** — currently `/opt/anaconda3/bin/python3`. Customers on a different Python setup (venv, pyenv, system Python) will need to update this. Consider documenting it in the customer project README or making it a comment in the generated file.

- [x] ~~**Hetzner server setup per customer**~~ — resolved: production deployment is handled entirely by **hof-os** (server provisioning, Docker Compose generation, rsync deploy, DNS, Traefik SSL). Customer repos only need a `Dockerfile`. The `docker-compose.yml` in customer repos is for **local development only**. No GitHub Actions deploy workflow needed.

- [ ] **More modules in hof-components** — currently only `lead-enrichment` exists. Candidates from the roadmap: `stripe-billing`, `email-outreach`. Build these as real customer needs come in and add them to `registry.json`.

- [ ] **Phase 6 maintenance tooling** — `hof add --diff <module>` and `hof add --update <module>` (show/apply upstream changes from hof-components). Useful once you have 10+ customers. Defer until then.

---

## Architecture Overview

The hof platform consists of three separate repositories and one npm package:

```
hof-engine          (pip package — the core framework runtime)
hof-components      (shadcn-style module registry — NOT a package, just a repo of copyable code)
@hof-engine/react   (npm package — React hooks for customer UIs)
customer-<name>     (one repo per customer — self-contained application)
```

### How They Relate

```
┌──────────────────────────────────────────────────────────────────┐
│  Customer Project Repo (e.g. acme-crm)                          │
│                                                                  │
│  pyproject.toml ──► pip install hof-engine (runtime dependency)  │
│  ui/package.json ──► npm install @hof-engine/react               │
│                                                                  │
│  tables/          ◄── copied from hof-components via CLI         │
│  functions/       ◄── copied from hof-components via CLI         │
│  flows/           ◄── copied from hof-components via CLI         │
│  cron/            ◄── copied from hof-components via CLI         │
│  ui/components/   ◄── copied from hof-components via CLI         │
│  ui/pages/        ◄── copied from hof-components via CLI         │
│                                                                  │
│  hof.config.py    (project configuration)                        │
│  .env             (secrets)                                      │
└──────────────────────────────────────────────────────────────────┘
```

The customer project is fully self-contained. If a customer leaves the agency, they take their repo, run `pip install hof-engine` and `hof dev`, and everything works. No dependency on hof-components at runtime.

---

## Part 1: Make hof-engine Distributable via pip

### 1.1 Pre-build the Admin UI

**Problem:** The admin UI at `hof/ui/admin/` currently contains raw source + `node_modules/`. Shipping `node_modules` inside a pip wheel is fragile (platform-specific binaries, massive size).

**Solution:** Add a build step that compiles the admin UI to static assets before packaging.

**Steps:**

1. Add a `hof/ui/admin/vite.config.ts` build configuration (if not already present) that outputs to `hof/ui/admin/dist/`.

2. Create a hatch build hook (`hatch_build.py` at repo root) that runs `npm ci && npm run build` inside `hof/ui/admin/` before the wheel is built:

```python
# hatch_build.py
import subprocess
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

class AdminBuildHook(BuildHookInterface):
    PLUGIN_NAME = "admin-build"

    def initialize(self, version, build_data):
        admin_dir = Path(self.root) / "hof" / "ui" / "admin"
        if not (admin_dir / "dist").exists():
            subprocess.run(["npm", "ci"], cwd=str(admin_dir), check=True)
            subprocess.run(["npm", "run", "build"], cwd=str(admin_dir), check=True)
```

3. Update `pyproject.toml` to use the build hook and include only `dist/` (not `node_modules/`):

```toml
[tool.hatch.build.targets.wheel]
packages = ["hof"]

[tool.hatch.build.targets.wheel.force-include]
"hof/ui/admin/dist" = "hof/ui/admin/dist"

[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
```

4. Add to `hof/ui/admin/.gitignore`:
```
dist/
```

5. Update the FastAPI static file serving in the engine to serve from `hof/ui/admin/dist/` instead of the raw source directory. The relevant code is in `hof/api/` — the admin routes should mount `StaticFiles(directory=admin_dist_path)`.

6. Add `node_modules/` under `hof/ui/admin/` to the wheel exclude list so it never ships.

### 1.2 Publish to a Private PyPI Index

**Options (pick one):**

- **GitHub Packages (PyPI):** Free for private repos. Authenticate via `GITHUB_TOKEN`. Customers install with `pip install hof-engine --index-url https://...`.
- **AWS CodeArtifact:** If already on AWS. Integrates with IAM.
- **Cloudflare R2 + `dumb-pypi`:** Cheapest self-hosted option. Static file hosting.
- **Public PyPI:** If you decide to open-source the engine later.

**Recommended for now:** GitHub Packages. It's free, private, and you're already on GitHub.

**Steps:**

1. Create a GitHub Actions workflow `.github/workflows/publish.yml`:

```yaml
name: Publish to GitHub Packages
on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - run: pip install hatch
      - run: hatch build
      - run: hatch publish --repo https://upload.pypi.org/legacy/  # or GitHub Packages URL
        env:
          HATCH_INDEX_USER: __token__
          HATCH_INDEX_AUTH: ${{ secrets.PYPI_TOKEN }}
```

2. Version management: Use `hatch version` commands or manually bump in `pyproject.toml`. Consider using `hatch-vcs` for git-tag-based versioning later.

### 1.3 Publish @hof-engine/react to npm

**Current state:** The `hof-react/` directory contains the React hooks package (`@hof-engine/react`). It has no build step — it ships raw TypeScript (`"main": "src/index.ts"`).

**Steps:**

1. Add a build step to `hof-react/` (use `tsup` or `tsconfig` to compile to JS + type declarations):

```json
{
  "scripts": {
    "build": "tsup src/index.ts --format esm,cjs --dts"
  },
  "main": "dist/index.cjs",
  "module": "dist/index.js",
  "types": "dist/index.d.ts",
  "files": ["dist"]
}
```

2. Publish to npm (public or private scope):
```bash
cd hof-react
npm publish --access public  # or --access restricted for private
```

3. The `ViteManager` in `hof/ui/vite.py` already generates a `package.json` for customer projects. Update `_create_package_json()` to include `@hof-engine/react` as a dependency:

```python
"dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "@hof-engine/react": "^0.1.0",  # add this
},
```

---

## Part 2: The hof-components Repository (shadcn-style)

### 2.1 Repository Structure

Create a new repo `hof-components` with this structure:

```
hof-components/
├── registry.json                  # master index of all available modules
├── modules/
│   ├── stripe-billing/
│   │   ├── module.json            # metadata, dependencies, description
│   │   ├── tables/
│   │   │   └── invoice.py
│   │   ├── functions/
│   │   │   └── webhooks.py
│   │   ├── flows/
│   │   │   └── payment_flow.py
│   │   └── ui/
│   │       ├── components/
│   │       │   └── InvoiceTable.tsx
│   │       └── pages/
│   │           └── billing.tsx
│   ├── email-outreach/
│   │   ├── module.json
│   │   ├── tables/
│   │   │   └── email_campaign.py
│   │   ├── functions/
│   │   │   └── send_email.py
│   │   └── ...
│   ├── lead-enrichment/
│   │   └── ...
│   └── ...
├── templates/                     # full project templates (compose modules)
│   ├── crm/
│   │   ├── template.json          # which modules to include + base config
│   │   ├── hof.config.py
│   │   ├── tables/
│   │   ├── functions/
│   │   ├── flows/
│   │   └── ui/
│   └── support-desk/
│       └── ...
└── README.md
```

### 2.2 module.json Schema

Each module has a `module.json` that describes it:

```json
{
  "name": "stripe-billing",
  "description": "Stripe payment integration with invoices, webhooks, and payment flows.",
  "version": "0.1.0",
  "engine": ">=0.1.0",
  "dependencies": {
    "pip": ["stripe>=8.0.0"],
    "npm": [],
    "modules": []
  },
  "files": {
    "tables": ["tables/invoice.py"],
    "functions": ["functions/webhooks.py"],
    "flows": ["flows/payment_flow.py"],
    "ui/components": ["ui/components/InvoiceTable.tsx"],
    "ui/pages": ["ui/pages/billing.tsx"]
  },
  "env_vars": [
    {"name": "STRIPE_SECRET_KEY", "description": "Stripe API secret key", "required": true},
    {"name": "STRIPE_WEBHOOK_SECRET", "description": "Stripe webhook signing secret", "required": true}
  ],
  "post_install_notes": "Run `hof db migrate` after adding this module to create the invoice table."
}
```

### 2.3 template.json Schema

Each template references modules and provides a base project:

```json
{
  "name": "crm",
  "description": "CRM application with lead management, email outreach, and billing.",
  "engine": ">=0.1.0",
  "modules": ["lead-enrichment", "email-outreach", "stripe-billing"],
  "post_install_notes": "Configure .env with required API keys, then run `hof db migrate && hof dev`."
}
```

### 2.4 registry.json

A flat index at the repo root for the CLI to read:

```json
{
  "modules": {
    "stripe-billing": {
      "description": "Stripe payment integration",
      "path": "modules/stripe-billing"
    },
    "email-outreach": {
      "description": "Email campaign management",
      "path": "modules/email-outreach"
    },
    "lead-enrichment": {
      "description": "AI-powered lead enrichment with human review",
      "path": "modules/lead-enrichment"
    }
  },
  "templates": {
    "crm": {
      "description": "CRM with leads, email, and billing",
      "path": "templates/crm"
    },
    "support-desk": {
      "description": "Customer support ticket system",
      "path": "templates/support-desk"
    }
  }
}
```

---

## Part 3: The `hof add` CLI Command

### 3.1 Overview

Add a new CLI command group to `hof/cli/commands/` that fetches modules from the `hof-components` repo and copies them into the current project. Modeled after `npx shadcn add <component>`.

### 3.2 Commands

```
hof add <module>              # Copy a module's files into the current project
hof add --list                # List all available modules
hof add --template <name>     # Scaffold a project from a template (alternative to hof new project)
```

### 3.3 Implementation: `hof/cli/commands/add.py`

**How it fetches modules:**

The CLI fetches from the `hof-components` GitHub repo. Two strategies (pick one):

- **Option A (simpler):** Clone/pull the `hof-components` repo to a local cache (`~/.hof/components/`) and copy from there. Works offline after first clone.
- **Option B (no local clone):** Use the GitHub API / raw.githubusercontent.com to fetch individual files. No local cache needed but requires network for every `hof add`.

**Recommended: Option A.** It's faster, works offline, and you can pin to a specific branch/tag.

**Detailed behavior of `hof add <module>`:**

1. Ensure `~/.hof/components/` exists. If not, clone `hof-components` repo there. If it exists, `git pull` to update.
2. Read `registry.json` to find the module.
3. Read the module's `module.json`.
4. For each file listed in `module.json.files`:
   - Copy it to the corresponding directory in the current project (e.g., `tables/invoice.py` goes to `./tables/invoice.py`).
   - If the destination file already exists, warn and skip (do NOT overwrite by default). Provide a `--force` flag to overwrite.
5. If `module.json.dependencies.pip` is non-empty, print a message: "Add these to your pyproject.toml: stripe>=8.0.0" (or auto-add them).
6. If `module.json.dependencies.npm` is non-empty, print a message to add them to `ui/package.json`.
7. If `module.json.dependencies.modules` is non-empty, prompt to install those first.
8. If `module.json.env_vars` is non-empty, append placeholder entries to `.env` (if not already present).
9. Print `module.json.post_install_notes`.

**Pseudocode:**

```python
# hof/cli/commands/add.py

import json
import shutil
import subprocess
from pathlib import Path
import typer
from rich.console import Console

app = typer.Typer()
console = Console()

COMPONENTS_REPO = "https://github.com/<org>/hof-components.git"
CACHE_DIR = Path.home() / ".hof" / "components"


def _ensure_cache():
    """Clone or update the hof-components repo in the local cache."""
    if not CACHE_DIR.exists():
        subprocess.run(["git", "clone", COMPONENTS_REPO, str(CACHE_DIR)], check=True)
    else:
        subprocess.run(["git", "pull"], cwd=str(CACHE_DIR), check=True)


def _load_registry() -> dict:
    return json.loads((CACHE_DIR / "registry.json").read_text())


def _load_module_meta(module_path: Path) -> dict:
    return json.loads((module_path / "module.json").read_text())


@app.callback(invoke_without_command=True)
def add(
    module_name: str = typer.Argument(None, help="Module name to add."),
    list_modules: bool = typer.Option(False, "--list", "-l", help="List available modules."),
    template: str = typer.Option(None, "--template", "-t", help="Create project from template."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
):
    _ensure_cache()
    registry = _load_registry()

    if list_modules:
        # Print all available modules and templates
        ...
        return

    if template:
        # Scaffold from template
        ...
        return

    if not module_name:
        console.print("[red]Provide a module name or use --list[/]")
        raise typer.Exit(1)

    if module_name not in registry["modules"]:
        console.print(f"[red]Module '{module_name}' not found.[/]")
        raise typer.Exit(1)

    module_rel_path = registry["modules"][module_name]["path"]
    module_path = CACHE_DIR / module_rel_path
    meta = _load_module_meta(module_path)

    project_root = Path.cwd()
    copied = []
    skipped = []

    for dest_dir, files in meta["files"].items():
        for file_rel in files:
            src = module_path / file_rel
            dst = project_root / file_rel
            if dst.exists() and not force:
                skipped.append(str(file_rel))
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(str(file_rel))

    for f in copied:
        console.print(f"  [green]+ {f}[/]")
    for f in skipped:
        console.print(f"  [yellow]~ {f} (exists, skipped)[/]")

    # Handle pip dependencies
    pip_deps = meta.get("dependencies", {}).get("pip", [])
    if pip_deps:
        console.print(f"\n[bold]Add to pyproject.toml dependencies:[/]")
        for dep in pip_deps:
            console.print(f"  {dep}")

    # Handle env vars
    env_vars = meta.get("env_vars", [])
    if env_vars:
        env_file = project_root / ".env"
        existing_env = env_file.read_text() if env_file.exists() else ""
        additions = []
        for var in env_vars:
            if var["name"] not in existing_env:
                additions.append(f'# {var["description"]}\n{var["name"]}=\n')
        if additions:
            with open(env_file, "a") as f:
                f.write("\n".join(additions))
            console.print(f"\n[bold]Added env vars to .env (fill in values):[/]")
            for var in env_vars:
                console.print(f"  {var['name']}: {var['description']}")

    # Post-install notes
    notes = meta.get("post_install_notes")
    if notes:
        console.print(f"\n[bold]Note:[/] {notes}")
```

### 3.4 Register the Command

In `hof/cli/main.py`, add:

```python
from hof.cli.commands import add as add_cmd

_typer_app.add_typer(add_cmd.app, name="add", help="Add modules from hof-components.")
```

---

## Part 4: Customer Project Structure

### 4.1 What a Customer Project Looks Like

After running `hof new project acme-crm` and `hof add stripe-billing` and `hof add email-outreach`:

```
acme-crm/
├── pyproject.toml              # or just requirements.txt
│   # dependencies:
│   #   hof-engine>=0.1.0
│   #   stripe>=8.0.0           (from stripe-billing module)
│   #   resend>=1.0.0           (from email-outreach module)
├── hof.config.py
├── .env
│   # DATABASE_URL=...
│   # REDIS_URL=...
│   # STRIPE_SECRET_KEY=        (added by hof add stripe-billing)
│   # STRIPE_WEBHOOK_SECRET=    (added by hof add stripe-billing)
│   # RESEND_API_KEY=           (added by hof add email-outreach)
├── tables/
│   ├── __init__.py
│   ├── invoice.py              ◄ from stripe-billing module (now owned by this project)
│   ├── email_campaign.py       ◄ from email-outreach module
│   └── lead.py                 ◄ custom for this customer
├── functions/
│   ├── __init__.py
│   ├── webhooks.py             ◄ from stripe-billing module
│   ├── send_email.py           ◄ from email-outreach module
│   └── import_leads.py         ◄ custom
├── flows/
│   ├── __init__.py
│   ├── payment_flow.py         ◄ from stripe-billing module
│   └── enrich_lead.py          ◄ custom
├── cron/
│   ├── __init__.py
│   └── re_enrich.py            ◄ custom
└── ui/
    ├── package.json            ◄ auto-generated by ViteManager
    ├── components/
    │   ├── InvoiceTable.tsx     ◄ from stripe-billing module
    │   └── LeadReview.tsx       ◄ custom
    └── pages/
        ├── billing.tsx          ◄ from stripe-billing module
        └── leads.tsx            ◄ custom
```

### 4.2 Key Principle: Once Copied, You Own It

After `hof add stripe-billing`, the files in `tables/invoice.py`, `functions/webhooks.py`, etc. are **part of the customer project**. They are regular files, not symlinks, not references. You can:

- Edit them freely for this customer.
- Delete files you don't need.
- Add fields to tables, modify flows, restyle UI components.

There is no runtime link back to `hof-components`. The customer project depends only on `hof-engine` (pip) and `@hof-engine/react` (npm).

### 4.3 Tracking Module Origin (Optional, for Maintainability)

To help you know which files came from which module (useful when you want to backport a fix), add a `.hof/modules.json` file to the customer project that `hof add` maintains:

```json
{
  "installed_modules": {
    "stripe-billing": {
      "version": "0.1.0",
      "installed_at": "2026-02-27T10:00:00Z",
      "files": [
        "tables/invoice.py",
        "functions/webhooks.py",
        "flows/payment_flow.py",
        "ui/components/InvoiceTable.tsx",
        "ui/pages/billing.tsx"
      ]
    },
    "email-outreach": {
      "version": "0.1.0",
      "installed_at": "2026-02-27T10:05:00Z",
      "files": [
        "tables/email_campaign.py",
        "functions/send_email.py"
      ]
    }
  }
}
```

This is metadata only — it has no runtime effect. It just helps you answer: "which customers have the stripe-billing module, and which version did they start from?"

A future `hof add --diff stripe-billing` command could show what changed between the current project's files and the latest version in `hof-components`, making it easier to backport fixes.

---

## Part 5: Deployment to Hetzner

### 5.1 Per-Customer Deployment

Each customer project is its own GitHub repo, deployed to its own Hetzner server. The deployment flow:

```
git push (customer repo) ──► GitHub Actions ──► SSH to Hetzner server ──► pull + restart
```

### 5.2 Suggested Deploy Script

Each customer repo should include a `deploy/` directory (or the `hof new project` scaffold generates it):

```
deploy/
├── docker-compose.yml          # PostgreSQL, Redis, app
├── Dockerfile                  # Python + Node runtime
├── nginx.conf                  # reverse proxy
└── .github/workflows/deploy.yml
```

**Dockerfile:**

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install .

COPY . .
RUN cd ui && npm install && npx vite build

EXPOSE 8000
CMD ["hof", "dev", "--host", "0.0.0.0", "--port", "8000"]
```

**docker-compose.yml:**

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
      - redis

  db:
    image: postgres:16
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  redis:
    image: redis:7-alpine

  worker:
    build: .
    command: celery -A hof.tasks.worker worker --loglevel=info
    env_file: .env
    depends_on:
      - db
      - redis

volumes:
  pgdata:
```

### 5.3 Scaffold This in `hof new project`

Update `hof/cli/commands/new.py` to include the deploy scaffold. Add these to `PROJECT_FILES`:

- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/deploy.yml`

---

## Part 6: Implementation Roadmap (Ordered)

### Phase 1: Make hof-engine pip-installable (Priority: HIGH)

1. **Pre-build admin UI:** Add hatch build hook to compile `hof/ui/admin/` to static assets. Update FastAPI to serve from `dist/`.
2. **Exclude node_modules from wheel:** Ensure `hof/ui/admin/node_modules/` is excluded from the built wheel.
3. **Test pip install:** `hatch build && pip install dist/hof_engine-0.1.0-py3-none-any.whl` in a fresh venv. Verify `hof --version`, `hof new project test-app`, and `hof dev` all work.
4. **Publish to GitHub Packages (or PyPI):** Set up the GitHub Actions publish workflow.

### Phase 2: Publish @hof-engine/react to npm (Priority: HIGH)

1. **Add build step** to `hof-react/` (tsup or tsc).
2. **Publish** to npm (public scope `@hof-engine/react`).
3. **Update ViteManager** to include `@hof-engine/react` in generated `package.json`.

### Phase 3: Create hof-components repo (Priority: MEDIUM)

1. **Create the repo** with the structure described in Part 2.
2. **Extract the example/ into the first module/template.** The current `example/` directory is a lead-enrichment app — extract it as both a `lead-enrichment` module and a `crm` template.
3. **Write registry.json and module.json** for the first module.
4. **Build 2-3 more modules** from real customer needs as they come.

### Phase 4: Build the `hof add` CLI command (Priority: MEDIUM)

1. **Implement `hof add`** as described in Part 3.
2. **Implement `.hof/modules.json` tracking.**
3. **Implement `hof add --list`** to show available modules.
4. **Implement `hof add --template`** to scaffold from a template (composes multiple modules).

### Phase 5: Deployment scaffold (Priority: LOW)

1. **Add Dockerfile, docker-compose.yml, deploy workflow** to `hof new project` scaffold.
2. **Test end-to-end:** `hof new project test` → `hof add lead-enrichment` → `docker compose up` → verify everything works.

### Phase 6: Maintenance tooling (Priority: LOW, do when you have 10+ customers)

1. **`hof add --diff <module>`**: Show diff between project's version of a module and latest in hof-components.
2. **`hof add --update <module>`**: Attempt to apply upstream changes (like a patch). Warn on conflicts.
3. **Cross-customer scripts:** A script that iterates over all customer repos and runs a command (e.g., bump hof-engine version, apply a security patch).

---

## Key Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Engine distribution | Private pip package (GitHub Packages) | Versioned, clean, customer can self-host |
| Module distribution | shadcn-style copy via `hof add` CLI | Full ownership, no runtime coupling, maximum flexibility |
| React hooks | npm package `@hof-engine/react` | Standard npm distribution, auto-included by ViteManager |
| Admin UI in wheel | Pre-built static assets only | Avoids shipping node_modules in pip package |
| Customer project | Standalone repo, pip depends on hof-engine | Self-contained, portable, customer can leave agency |
| Module tracking | `.hof/modules.json` metadata file | Helps with maintenance without runtime coupling |
| Deployment | Docker Compose per customer on Hetzner | Isolated, reproducible, includes PostgreSQL + Redis |
| Module registry | Separate `hof-components` GitHub repo | Clean separation, browsable, cacheable |
