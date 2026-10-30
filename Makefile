# Raccourcis. Développement : make install / make check. Installation : docs/exploitation/installation.md.
.PHONY: init install check lint test migrations-test upgrade-test audit image deploy restore-test preflight dev openapi \
	release tag web trial reference

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

web:  # app web : lint (Biome) et tests des modules (node --test) ; Node 22
	npx --yes @biomejs/biome@2.5.15 lint
	node --test "tests/web/*.test.mjs"

trial:  # instance d'essai jetable : l'image TAG migre des données fictives et répond
	@test -n "$(TAG)" || (echo "usage : make trial TAG=v0.12.0" && exit 1)
	deploy/trial.sh $(TAG)

upgrade-test:  # bases de la dernière version taguée, migrées par le code courant
	scripts/upgrade_from_previous.sh

audit:  # vulnérabilités connues des dépendances livrées (images hub et collecteurs)
	uv export --frozen --all-extras --no-dev --no-emit-project -q -o .audit-requirements.txt
	uvx --quiet pip-audit==2.10.0 -r .audit-requirements.txt --require-hashes --disable-pip \
	  --progress-spinner off; status=$$?; rm -f .audit-requirements.txt; exit $$status

check: lint test migrations-test

assistant-test:  # l'assistant (assistant/) : ruff, mypy, pytest, dans assistant/.venv
	cd assistant && python3.12 -m venv .venv && .venv/bin/pip -q install -r requirements-dev.txt -e .. && \
	  .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check . && \
	  .venv/bin/python -m mypy && .venv/bin/python -m pytest -q
	cd assistant/eventkit && ../.venv/bin/pip -q install -r requirements-dev.txt && ../.venv/bin/python -m pytest -q

domia-contract:  # reprend le contrat avec Domia depuis un clone : make domia-contract DOMIA=~/domia
	scripts/domia_contract.sh "$(DOMIA)"

reference:  # docs/reference/ (routes, outils, connecteurs), après un changement voulu
	UPDATE_REFERENCE=1 uv run pytest -q tests/test_reference_docs.py

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

release:  # sur une branche : prépare la PR de version (pyproject, uv.lock, CHANGELOG)
	@test -n "$(VERSION)" || (echo "usage : make release VERSION=0.12.0" && exit 1)
	uv run python scripts/release.py prepare $(VERSION)

tag:  # sur main à jour, après la fusion de la PR de version : le tag publie les images
	@test "$$(git rev-parse --abbrev-ref HEAD)" = main || (echo "tag : se placer sur main" && exit 1)
	@git diff --quiet HEAD && git fetch -q origin main && test "$$(git rev-parse HEAD)" = "$$(git rev-parse origin/main)" \
	  || (echo "tag : main doit être propre et à jour" && exit 1)
	@uv run python scripts/release.py check v$$(uv run python -c 'import hub; print(hub.__version__)')
	v=v$$(uv run python -c 'import hub; print(hub.__version__)'); git tag -a $$v -m $$v && git push origin $$v

restore-test:
	deploy/restore-test.sh $(TAG)
