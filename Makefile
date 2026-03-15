.PHONY: check lint format test

check: lint test
	@echo "All checks passed."

lint:
	ruff check hof/ tests/
	ruff format --check hof/ tests/

format:
	ruff format hof/ tests/

test:
	pytest tests/ -m "not integration" -v
