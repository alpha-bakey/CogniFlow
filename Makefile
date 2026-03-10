.PHONY: help install dev-install test lint format clean docker-up docker-down migrate demo

# Default target
help:
	@echo "CogniFlow Development Commands"
	@echo "=============================="
	@echo "install       - Install production dependencies"
	@echo "dev-install   - Install with dev dependencies"
	@echo "test          - Run test suite"
	@echo "test-cov      - Run tests with coverage"
	@echo "lint          - Run linting (ruff, mypy)"
	@echo "format        - Format code (black)"
	@echo "clean         - Clean build artifacts"
	@echo "docker-up     - Start Docker services (postgres, redis)"
	@echo "docker-down   - Stop Docker services"
	@echo "migrate       - Run database migrations"
	@echo "demo          - Run demo script"
	@echo "server        - Start API server"
	@echo "docs          - Generate documentation"

# Installation
install:
	pip install -e .

dev-install:
	pip install -e ".[dev]"

# Testing
test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=cogniflow --cov-report=html --cov-report=term

# Code quality
lint:
	ruff check src/
	mypy src/cogniflow

format:
	black src/ tests/
	ruff check --fix src/

format-check:
	black --check src/ tests/

# Cleaning
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Docker
docker-up:
	docker-compose up -d postgres redis

docker-down:
	docker-compose down

docker-build:
	docker-compose build

docker-logs:
	docker-compose logs -f

# Database
migrate:
	python -c "from cogniflow.models.database import init_db; import asyncio; asyncio.run(init_db())"
	@echo "Database tables created"

reset-db:
	docker-compose down -v
	docker-compose up -d postgres redis
	@echo "Waiting for database..."
	@sleep 3
	make migrate

# Demo and server
demo:
	python examples/demo.py

server:
	uvicorn cogniflow.server:app --host 0.0.0.0 --port 8000 --reload

# Development workflow
setup: dev-install docker-up migrate
	@echo "Development environment ready!"

all-check: format-check lint test
	@echo "All checks passed!"
