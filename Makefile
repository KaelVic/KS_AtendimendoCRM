.PHONY: help install up up-openwa down logs test lint typecheck build

help:
	@echo "Comandos disponíveis no KS Atendimento IA:"
	@echo "  make up          - Sobe a stack essencial (Postgres, Redis, API, Worker, Web, ScrapeGraph)"
	@echo "  make up-openwa   - Sobe a stack incluindo o profile opcional openwa"
	@echo "  make down        - Encerra todos os contêineres"
	@echo "  make logs        - Exibe logs unificados dos contêineres"
	@echo "  make test        - Executa suíte de testes"
	@echo "  make lint        - Executa verificação de lint"

up:
	docker compose up -d

up-openwa:
	docker compose --profile openwa up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	pytest -q tests apps/api/tests apps/worker/tests services/scrapegraph/tests tests/e2e

lint:
	ruff check apps/api
	npm --prefix apps/web run lint

install:
	python -m pip install -r apps/api/requirements.txt
	npm --prefix apps/web ci

typecheck:
	npm --prefix apps/web run typecheck

build:
	npm --prefix apps/web run build
