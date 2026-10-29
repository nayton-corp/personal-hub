# Versions et publication

Le hub porte **une seule version** SemVer, celle de `pyproject.toml` ([D-008](decisions.md)).
L'image, `/api/health`, le tag git et les notes de version la partagent. Une version se publie
par un tag `vX.Y.Z` ; le déploiement reste manuel, sur ce tag, après un « oui déploie vX »
([D-007](decisions.md)).

## La chaîne

1. **Une PR** passe toute la CI (`.github/workflows/ci.yml`) : données fictives seulement,
   secrets (gitleaks), ruff, mypy strict, contrats import-linter, tests à 85 %, migrations de
   zéro, **migration depuis la version précédente**, version cohérente, **pip-audit**, images
   arm64 construites puis jetées. Fusion en squash.
2. **La PR de version**, sur une branche à jour de main :

   ```
   make release VERSION=0.12.0
   ```

   Elle passe la version dans `pyproject.toml` et `uv.lock`, et range sous `## [0.12.0] · date`
   tout ce qui était « Non publié » dans le CHANGELOG (une nouvelle section « Non publié », vide,
   reste en tête). Refusée si la version ne suit pas l'actuelle ou si rien n'est à publier.
3. **Le tag**, sur main à jour après la fusion :

   ```
   make tag
   ```

   Il vérifie la version et pousse `v0.12.0`. Le workflow `.github/workflows/release.yml`
   repasse toutes les barrières, pousse les trois images linux/arm64 sur GHCR
   (`ghcr.io/nayton-corp/personal-hub/{hub,web,collector}:v0.12.0`, et `:v0.12`) avec leur
   SBOM et leur provenance, les analyse (Trivy : une vulnérabilité critique corrigeable arrête
   la publication) puis crée la release GitHub : notes tirées du CHANGELOG, empreintes des
   images, rapports Trivy.
4. **Le déploiement**, sur le Mac, après « oui déploie v0.12.0 » :

   ```
   git fetch --tags && git checkout v0.12.0
   make deploy TAG=v0.12.0
   ```

   `deploy/deploy.sh` exige que le clone soit sur le tag (compose, crontab et scripts du même
   commit), tire les images, vérifie que l'image porte bien la version du tag, puis fait comme
   avant : `verify`, copie des bases, migrations, second `verify`, démarrage, `/api/health`,
   retour arrière seul au moindre échec. Le clone reste sur le tag : `hubc` et les commandes à
   la main lisent le même `compose.yaml` que les conteneurs.

Un nom qui n'est pas un tag git `vX.Y.Z` du clone (`dev`, `essai`, ou une version jamais
taguée comme les v0.11.x d'avant S13), ou `HUB_BUILD=1`, construit les images sur le Mac depuis
le clone, comme avant.

## Une fois sur le Mac : accès à GHCR

Le dépôt est privé, ses images aussi. Crée un jeton GitHub *classic* limité à
`read:packages` (Settings → Developer settings → Personal access tokens), puis :

```
docker login ghcr.io -u <ton-compte-github>
```

Colle le jeton quand le mot de passe est demandé. Docker Desktop le garde dans le Trousseau.
`HUB_REGISTRY` dans `deploy/.env` change de registre (un autre hub, un fork).

## Mises à jour des dépendances

Dependabot (`.github/dependabot.yml`) ouvre chaque lundi une PR groupée par écosystème :
paquets Python (`uv.lock`), actions GitHub, images de `deploy/compose.yaml`. Elles passent la
CI comme les autres et ne se fusionnent jamais seules. Les images de base du `Dockerfile`,
épinglées par empreinte, se mettent à jour à la main.

## Commandes

| Commande | Effet |
| --- | --- |
| `make audit` | pip-audit des dépendances livrées (images hub et collecteurs) |
| `make upgrade-test` | bases et relevé fictifs créés par la dernière version taguée, migrés et vérifiés par le code courant |
| `make release VERSION=X.Y.Z` | prépare la PR de version |
| `make tag` | pose et pousse le tag de la version de `pyproject.toml` (sur main) |
| `python scripts/release.py notes vX.Y.Z` | notes de version d'un tag |
