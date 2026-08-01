# ============================================================
# TSAR — Makefile
# ============================================================
# Common commands. Run `make help` for list.

.PHONY: help install install-dev lint format typecheck test run run-dry \
       docker-build docker-up docker-down docker-logs clean migrate migrate-rollback

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

# --- Database Migrations ---

DB_PATH ?= data/tsar.db

migrate: ## Run all pending SQL migrations
	@echo "Running migrations against $(DB_PATH)..."
	@mkdir -p data
	@for f in migrations/*.sql; do \
		case "$$f" in *rollback*) continue ;; esac; \
		version=$$(basename "$$f" | grep -oP '^\d+'); \
		name=$$(basename "$$f"); \
		already=$$(sqlite3 "$(DB_PATH)" "SELECT version FROM schema_migrations WHERE version=$$version" 2>/dev/null || echo ""); \
		if [ -z "$$already" ]; then \
			echo "  ▶ Applying $$name"; \
		sqlite3 "$(DB_PATH)" < "$$f" || { echo "  ✗ FAILED: $$name"; exit 1; }; \
		else \
			echo "  ✓ Already applied: $$name"; \
		fi; \
	done
	@echo "✅ All migrations applied."

migrate-rollback: ## Rollback last migration
	@echo "Rolling back last migration from $(DB_PATH)..."
	@last=$$(sqlite3 "$(DB_PATH)" "SELECT MAX(version) FROM schema_migrations" 2>/dev/null || echo ""); \
	if [ -z "$$last" ]; then echo "No migrations to rollback."; exit 0; fi; \
	rollback="migrations/$$(printf '%03d' $$last)_"*.rollback.sql; \
	if [ -f $$rollback ]; then \
		echo "  ◀ Rolling back version $$last"; \
		sqlite3 "$(DB_PATH)" < $$rollback || { echo "  ✗ ROLLBACK FAILED"; exit 1; }; \
		echo "✅ Rolled back version $$last."; \
	else \
		echo "  ✗ No rollback script found for version $$last"; \
		exit 1; \
	fi

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

# --- One-Command Setup ---

setup: ## 🚀 One-command setup — install, configure, test, run
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║         TSAR — Trading Super Agent for Returns      ║"
	@echo "║                 One-Command Setup                    ║"
	@echo "╚══════════════════════════════════════════════════════╝"
	@echo ""
	@echo "Step 1/5: Installing dependencies..."
	@pip install -e ".[dev]" 2>&1 | tail -3
	@echo ""
	@echo "Step 2/5: Checking Python version..."
	@python -c "import sys; v=sys.version_info; assert v >= (3,12), f'Need Python 3.12+, got {v.major}.{v.minor}'; print(f'  ✅ Python {v.major}.{v.minor}.{v.micro}')"
	@echo ""
	@echo "Step 3/5: Creating data directory..."
	@mkdir -p data
	@echo "  ✅ data/ created"
	@echo ""
	@echo "Step 4/5: Running setup wizard..."
	@python scripts/setup.py
	@echo ""
	@echo "Step 5/5: Running tests..."
	@python -m pytest tests/ -v --tb=short -q 2>&1 | tail -5
	@echo ""
	@echo "╔══════════════════════════════════════════════════════╗"
	@echo "║                 Setup Complete!                      ║"
	@echo "╠══════════════════════════════════════════════════════╣"
	@echo "║  Start trading:    make run                          ║"
	@echo "║  Paper trading:    make run-dry                      ║"
	@echo "║  Run tests:        make test                         ║"
	@echo "║  Docker:           make docker-up                    ║"
	@echo "╚══════════════════════════════════════════════════════╝"
	@echo ""
