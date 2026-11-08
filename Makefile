.PHONY: help dev backend frontend test lint build up down logs

help:
	@echo "Ruleshelf"
	@echo "  make dev       Run backend (:8000) and frontend (:5173) with reload"
	@echo "  make test      Run backend tests and lint"
	@echo "  make build     Build the production container image"
	@echo "  make up        Run the published image with docker compose"
	@echo "  make down      Stop the compose stack"

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."

backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -q && ruff check app tests

lint:
	cd backend && ruff check app tests
	cd frontend && npm run build

build:
	docker build -t ruleshelf:local .

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f ruleshelf

# Local image instead of the published one:
up-build:
	docker compose -f compose.dev.yml up -d --build
