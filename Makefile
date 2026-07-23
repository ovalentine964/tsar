# ============================================================
# TSAR — Makefile
# ============================================================
# Common commands. Run `make help` for list.

.PHONY: help install install-dev lint format typecheck test run run-dry \
       docker-build docker-up docker-down docker-logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Python ---

install: ## Install production dependencies
	pip install .

install-dev: ## Install all dependencies (prod + dev)
	pip install -e ".[dev]"

lint: ## Run linter (ruff check)
	ruff check src/ tests/

format: ## Format code (ruff format + fix)
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Run type checker (mypy --strict)
	mypy src/

test: ## Run tests with coverage
	pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

test-fast: ## Run tests without coverage
	pytest tests/ -v --tb=short

# --- Application ---

run: ## Run the trading system
	python -m src

run-dry: ## Run in paper trading mode (no real trades)
	TSAR_TRADING_MODE=paper python -m src

run-api: ## Run API server only
	python -m src --api-only

# --- Docker ---

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start Docker services (detached)
	docker compose up -d

docker-down: ## Stop Docker services
	docker compose down

docker-logs: ## View Docker logs (follow)
	docker compose logs -f

docker-restart: ## Restart Docker services
	docker compose restart

# --- Maintenance ---

clean: ## Clean generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml

db-backup: ## Backup SQLite database
	@mkdir -p data/backups
	cp data/tsar.db data/backups/tsar_$$(date +%Y%m%d_%H%M%S).db 2>/dev/null || echo "No database file found"

redis-flush: ## Flush Redis (DEV ONLY — destroys all data!)
	@echo "⚠️  This will delete ALL Redis data. Press Ctrl+C to abort."
	@sleep 3
	docker compose exec redis redis-cli -a $${REDIS_PASSWORD:-tsar_dev_password} FLUSHDB
