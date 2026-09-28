.PHONY: up down test lint seed ingest ask investigate consolidate eval pr-check stats

up:
	docker compose up -d db redis
	@echo "Waiting for PostgreSQL and Redis to be healthy..."
	@sleep 3

down:
	docker compose down

test:
	pytest -v tests/

lint:
	ruff check .

seed:
	python cli.py seed

ingest:
	python cli.py ingest data/seed

ask:
	python cli.py ask "$(filter-out $@,$(MAKECMDGOALS))"

investigate:
	python cli.py investigate --scenario A_pool_exhaustion

consolidate:
	python cli.py consolidate

eval:
	python cli.py eval

pr-check:
	python cli.py pr-check

stats:
	python cli.py stats
