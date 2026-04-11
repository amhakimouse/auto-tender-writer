# =============================================================================
# Auto Tender Writer — Makefile
# One-command shortcuts for Docker Compose operations.
# Usage: Run these from the project root (where this Makefile lives).
#
# Prerequisites: Docker Desktop must be running.
# =============================================================================

.PHONY: help up down build logs shell db-shell migrate restart clean nuke

# Default target — show help
help:
	@echo ""
	@echo "  Auto Tender Writer — Docker Commands"
	@echo "  ────────────────────────────────────"
	@echo "  make up        Build images and start all services (API + DB + Redis)"
	@echo "  make down      Stop and remove containers (keeps volumes/data)"
	@echo "  make restart   Restart the API container only"
	@echo "  make build     Force-rebuild images without cache"
	@echo "  make logs      Stream live logs from the API container"
	@echo "  make shell     Open a bash shell inside the API container"
	@echo "  make db-shell  Open psql shell inside the Postgres container"
	@echo "  make migrate   Run Alembic migrations inside the API container"
	@echo "  make clean     Stop containers and remove all named volumes (DELETES DATA)"
	@echo "  make nuke      Full wipe: containers + volumes + built images"
	@echo ""

# ── Start everything ─────────────────────────────────────────────────────────
up:
	docker compose up --build -d
	@echo ""
	@echo "  ✅  Services started!"
	@echo "  📖  API docs  → http://localhost:8000/api/v1/docs"
	@echo "  💚  Health    → http://localhost:8000/health"
	@echo "  📋  Logs      → make logs"
	@echo ""

# ── Stop (keep volumes) ───────────────────────────────────────────────────────
down:
	docker compose down

# ── Force rebuild (clears Docker layer cache) ─────────────────────────────────
build:
	docker compose build --no-cache

# ── Stream logs ───────────────────────────────────────────────────────────────
logs:
	docker compose logs -f api

# ── Bash shell inside the running API container ───────────────────────────────
shell:
	docker compose exec api bash

# ── psql shell inside the Postgres container ─────────────────────────────────
db-shell:
	docker compose exec db psql -U atw_user -d atw_db

# ── Restart only the API (e.g. after a config change) ────────────────────────
restart:
	docker compose restart api

# ── Run Alembic DB migrations ─────────────────────────────────────────────────
migrate:
	docker compose exec api alembic upgrade head

# ── Stop + delete volumes (DATA LOSS WARNING) ─────────────────────────────────
clean:
	@echo "⚠️  This will DELETE all database data and uploaded files!"
	@read -p "Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	docker compose down -v

# ── Full wipe including built images ──────────────────────────────────────────
nuke:
	@echo "💥  Full wipe: containers, volumes, and images"
	docker compose down -v --rmi local
