.PHONY: dev lint format test build hooks hooks-install audit

dev:
	uv sync --all-groups

lint:
	uv run ruff format --check
	uv run ruff check
	uv run ty check src/

format:
	uv run ruff format .

test:
	uv run pytest

build:
	uv build

hooks:
	prek run --all-files

hooks-install:
	prek install

audit:
	uv run pip-audit .
