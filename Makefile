.PHONY: dev services migrate api worker test test-unit down

ALEMBIC := uv run --package robomcp-platform alembic -c packages/platform/alembic.ini

dev: services migrate api            ## compose up, migrate, run the API

services:                            ## start Postgres + MinIO and wait until healthy
	docker compose up -d --wait

migrate:                             ## apply all migrations to the dev database
	$(ALEMBIC) upgrade head

api:                                 ## run the API with reload on :8000
	uv run --package robomcp-platform uvicorn robomcp_platform.api.app:create_app --factory --reload --port 8000

worker:                              ## run one sim worker
	uv run --package robomcp-platform robomcp-worker

test: services                       ## unit + integration tests (throwaway test database)
	uv run --package robomcp-platform pytest packages/platform/tests

test-unit:                           ## unit tests only, no database
	uv run --package robomcp-platform pytest packages/platform/tests/unit

down:                                ## stop the services (data volumes are kept)
	docker compose down
