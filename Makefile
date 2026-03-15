.PHONY: check lint format test dev-component

check: lint test
	@echo "All checks passed."

lint:
	ruff check hof/ tests/
	ruff format --check hof/ tests/

format:
	ruff format hof/ tests/

test:
	pytest tests/ -m "not integration" -v

# -----------------------------------------------------------------------
# dev-component — scaffold a fresh hof app and run it on port 8001
#
# Usage:
#   make dev-component APP=mytest
#   make dev-component APP=mytest CLEAN=1   # wipe and recreate
#
# The app is created in /tmp/hof-dev-<APP>/ and reused on subsequent
# runs, so your test data persists between restarts.  Pass CLEAN=1 to
# start fresh.  hof-engine itself is installed in editable mode from
# this repo so live Python changes are reflected immediately.
# -----------------------------------------------------------------------

APP        ?=
CLEAN      ?= 0
_DEV_DIR   := /tmp/hof-dev-$(APP)
_HOF_PY    := $(_DEV_DIR)/.venv/bin/python
_HOF_BIN   := $(_DEV_DIR)/.venv/bin/hof

dev-component:
ifeq ($(strip $(APP)),)
	@echo "APP is required.  Usage: make dev-component APP=<name>"
	@exit 1
endif
	@# Optionally wipe previous run
	@if [ "$(CLEAN)" = "1" ] && [ -d "$(_DEV_DIR)" ]; then \
		echo "CLEAN=1: removing $(_DEV_DIR)"; \
		rm -rf "$(_DEV_DIR)"; \
	fi
	@# Create virtualenv if missing
	@if [ ! -d "$(_DEV_DIR)/.venv" ]; then \
		echo "Creating virtualenv..."; \
		uv venv --python 3.12 "$(_DEV_DIR)/.venv"; \
	fi
	@# Install hof-engine from this repo in editable mode
	@if [ ! -f "$(_DEV_DIR)/.venv/.hof-ready" ]; then \
		echo "Installing editable hof-engine from $(CURDIR)..."; \
		uv pip install --python "$(_HOF_PY)" -e "$(CURDIR)"; \
		touch "$(_DEV_DIR)/.venv/.hof-ready"; \
	fi
	@# Scaffold project files if not yet present
	@if [ ! -f "$(_DEV_DIR)/hof.config.py" ]; then \
		echo "Scaffolding new hof project '$(APP)' in $(_DEV_DIR)..."; \
		mkdir -p "$(_DEV_DIR)"; \
		cd "$(_DEV_DIR)" && "$(_HOF_BIN)" new project "$(APP)" && \
			cp -r "$(APP)/." . && rm -rf "$(APP)"; \
	fi
	@# Write .env pointing at the shared dev Postgres + Redis
	@if [ ! -f "$(_DEV_DIR)/.env" ]; then \
		printf 'DATABASE_URL=postgresql://hof:hof@localhost:5433/hof\nREDIS_URL=redis://localhost:6380/0\nHOF_ADMIN_PASSWORD=changeme\nDB_NAME=hof\nDB_PASSWORD=hof\n' \
			> "$(_DEV_DIR)/.env"; \
	fi
	@# Spin up infra (idempotent)
	@echo "Starting Postgres + Redis..."
	@docker compose up -d db redis --wait 2>/dev/null || docker compose up -d db redis
	@# Run migrations, then start dev server
	@echo "Running migrations..."
	@cd "$(_DEV_DIR)" && "$(_HOF_BIN)" db migrate
	@echo ""
	@echo "Starting hof dev server for '$(APP)' → http://localhost:8001/admin"
	@echo "  admin / changeme"
	@echo ""
	@cd "$(_DEV_DIR)" && "$(_HOF_BIN)" dev
