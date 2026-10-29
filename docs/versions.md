# Versions et publication

Le hub porte **une seule version** SemVer, celle de `pyproject.toml` ([D-008](decisions.md)).
L'image, `/api/health`, le tag git et les notes de version la partagent. Une version se publie
par un tag `vX.Y.Z` ; le déploiement reste manuel, sur ce tag, après un « oui déploie vX »
([D-007](decisions.md)).

## La chaîne

1. **Une PR** passe toute la CI (`.github/workflows/ci.yml`) : données fictives seulement,
   secrets (gitleaks), ruff, mypy strict, contrats import-linter, tests à 85 %, migrations de
   zéro, **migration depuis la version précédente**, version cohérente, **pip-audit**, lint et
   tests des modules de l'app web, **l'app à 375 px dans Chromium** sur un an de données
   fictives, images arm64 construites puis **essayées** (instance d'essai). Fusion en squash.
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
   commit), tire les images, vérifie que l'image porte bien la version du tag, lance
   l'instance d'essai (ci-dessous) et s'arrête si elle échoue, puis fait comme
   avant : `verify`, copie des bases, migrations, second `verify`, démarrage, `/api/health`,
   retour arrière seul au moindre échec. Le clone reste sur le tag : `hubc` et les commandes à
   la main lisent le même `compose.yaml` que les conteneurs.

Un nom qui n'est pas un tag git `vX.Y.Z` du clone (`dev`, `essai`, ou une version jamais
taguée comme les v0.11.x d'avant S13), ou `HUB_BUILD=1`, construit les images sur le Mac depuis
le clone, comme avant.

## Accès à GHCR depuis le Mac

Le dépôt est public (décision du 29.10.2026), ses images aussi : `docker pull` n'a besoin
d'aucune connexion. Elles ne contiennent que le code, jamais une donnée. Si le dépôt devient
privé, crée un jeton GitHub *classic* limité à `read:packages` (Settings → Developer settings →
Personal access tokens), puis, une fois :

```
docker login ghcr.io -u <ton-compte-github>
```

Colle le jeton quand le mot de passe est demandé. Docker Desktop le garde dans le Trousseau.
`HUB_REGISTRY` dans `deploy/.env` change de registre (un autre hub, un fork).

## Données fictives et instance d'essai

`scripts/demo_data.py` écrit un an de relevés camt.053 inventés pour deux comptes (courant et
épargne) : salaire, loyer, assurance, abonnements, courses, sorties, virement mensuel vers
l'épargne. Bibliothèque standard seulement, il tourne dans le venv comme dans l'image.

`deploy/trial.sh <tag> [précédent]` (`make trial TAG=…`) monte une instance jetable : l'image
de la version en place crée les bases et importe ces relevés, celle du tag les migre, passe
`hub verify` et `verify-ledger`, puis démarre l'API et attend `/api/health`. Volumes jetables,
aucun réseau, ni secret ni dossier du Mac. `make deploy` la lance avant de toucher aux vraies
bases (`HUB_SKIP_TRIAL=1` pour la sauter) ; la CI la lance sur l'image arm64 de chaque PR.

## L'app web

- **Lint** : Biome 2.5.15 (`biome.json`), règles recommandées, variables non déclarées ou
  inutilisées refusées. `make web` (Node 22).
- **Modules** : `node --test tests/web/*.test.mjs` (montants, dates, mois budgétaire).
- **Parcours** : `tests/web/test_app_mobile.py` sert l'app depuis l'API sur un an de données
  fictives, crée la première passkey avec l'authentificateur virtuel de Chromium, puis ouvre
  Accueil, Patrimoine, Budget, Journal et Sources à 375 px : aucune erreur JavaScript ni
  réponse 5xx, aucun défilement horizontal, du contenu. La CI garde les captures (artefact
  `captures-375px`).

## Mises à jour des dépendances

Dependabot (`.github/dependabot.yml`) ouvre chaque lundi une PR groupée par écosystème :
paquets Python (`uv.lock`), actions GitHub, images de `deploy/compose.yaml`. Elles passent la
CI comme les autres et ne se fusionnent jamais seules. Les images de base du `Dockerfile`,
épinglées par empreinte, se mettent à jour à la main.

## Commandes

| Commande | Effet |
| --- | --- |
| `make web` | lint et tests des modules de l'app (Node 22) |
| `make trial TAG=vX.Y.Z` | instance d'essai jetable de l'image du tag |
| `python3 scripts/demo_data.py <dossier>` | un an de relevés fictifs et `accounts.tsv` |
| `make audit` | pip-audit des dépendances livrées (images hub et collecteurs) |
| `make upgrade-test` | bases et relevé fictifs créés par la dernière version taguée, migrés et vérifiés par le code courant |
| `make release VERSION=X.Y.Z` | prépare la PR de version |
| `make tag` | pose et pousse le tag de la version de `pyproject.toml` (sur main) |
| `python scripts/release.py notes vX.Y.Z` | notes de version d'un tag |
