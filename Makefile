# Raccourcis. Développement : make install / make check. Installation : docs/installation.md.
.PHONY: init install check lint test migrations-test image deploy restore-test preflight dev openapi

install:
	uv sync --frozen
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports
	scripts/check_no_data.sh

test:
	uv run pytest -q --cov=hub --cov-fail-under=85

migrations-test:
	uv run pytest -q -m migrations

check: lint test migrations-test

openapi:  # après un changement voulu du contrat d'API
	UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py

dev:  # API locale sur http://localhost:8710, app servie par l'API, données dans ./var
	HUB_PATHS__DATA=var/data HUB_PATHS__INBOX=var/inbox HUB_PATHS__ARCHIVE=var/archive \
	HUB_PATHS__BACKUP=var/backup HUB_SERVER__WEB_ROOT=hub/web \
	uv run hub serve --migrate

image:
	docker build --platform linux/arm64 --target hub -t hub:dev .
	docker build --platform linux/arm64 --target web -t hub-web:dev .
	docker build --platform linux/arm64 --target collector -t hub-collector:dev .

init:  # première installation : clé age, secrets, dossiers, deploy/.env
	deploy/init.sh

preflight:
	deploy/mac-preflight.sh

deploy:
	@test -n "$(TAG)" || (echo "usage : make deploy TAG=v0.1.0" && exit 1)
	deploy/mac-preflight.sh
	deploy/deploy.sh $(TAG)

restore-test:
	deploy/restore-test.sh $(TAG)
