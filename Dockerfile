# syntax=docker/dockerfile:1.7
# Images linux/arm64 construites sur le Mac M1 Max ; les mêmes tournent sur le Pi 5 (arm64).
# Bases épinglées par version et par empreinte (index multi-architecture).
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG CADDY_IMAGE=caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
ARG RESTIC_IMAGE=restic/restic:0.18.1@sha256:39d9072fb5651c80d75c7a811612eb60b4c06b32ffe87c2e9f3c7222e1797e76

FROM ${RESTIC_IMAGE} AS restic

FROM ${PYTHON_IMAGE} AS build
RUN pip install --no-cache-dir uv==0.13.6
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/srv/hub/venv
WORKDIR /srv/hub/app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY hub ./hub
COPY deploy/crontab deploy/settings.toml ./deploy/
RUN uv sync --frozen --no-dev --no-editable

# --- API, importeur, planificateur : une seule image, des commandes différentes ---
FROM ${PYTHON_IMAGE} AS hub
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
# pdftotext (poppler) lit les PDF VIAC, comme les scripts du Mac (lot 4)
RUN apt-get update \
 && apt-get install --no-install-recommends -y poppler-utils \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 hub \
 && useradd --uid 10001 --gid 10001 --home-dir /srv/hub --shell /usr/sbin/nologin hub \
 && mkdir -p /srv/hub/data /srv/hub/archive /srv/hub/backup /srv/hub/inbox \
 && chown -R 10001:10001 /srv/hub \
 && chmod 0700 /srv/hub/data /srv/hub/archive /srv/hub/backup
COPY --from=build /srv/hub/venv /srv/hub/venv
COPY --from=build /srv/hub/app /srv/hub/app
ENV PATH=/srv/hub/venv/bin:$PATH \
    HUB_SETTINGS=/srv/hub/app/deploy/settings.toml \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Zurich
WORKDIR /srv/hub/app
USER 10001:10001
CMD ["hub", "serve", "--workers", "1"]

# --- Caddy : fichiers de l'app, en-têtes CSP, proxy /api ---
FROM ${CADDY_IMAGE} AS web
# le binaire officiel porte la capacité cap_net_bind_service, refusée par no-new-privileges :
# une copie sans attributs étendus suffit, puisqu'on écoute sur 8080 en utilisateur 10001
RUN cp /usr/bin/caddy /usr/local/bin/caddy && rm /usr/bin/caddy \
 && ln -s /usr/local/bin/caddy /usr/bin/caddy
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY hub/web /srv/web
