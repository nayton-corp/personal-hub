# Sécurité

Ce que le hub protège, contre qui, et comment. Un hub sert une seule personne ; ses données ne
quittent pas sa machine, sauf les sauvegardes chiffrées qu'elle choisit d'envoyer ailleurs.

## Ce qu'on protège

- Les données des domaines : écritures, soldes, contreparties, documents.
- Les secrets : identifiants des banques et des plateformes, clés d'API, mot de passe restic.
- L'intégrité du registre : une écriture effacée ou modifiée en douce doit se voir.

## Qui peut atteindre le hub

- **Réseau** : l'app n'est joignable que par le tailnet (Tailscale), jamais depuis Internet.
  `deploy/tailscale-acl.hujson` ne laisse que le propriétaire atteindre le port 443 du nœud
  `tag:hub` ; Tailscale termine le TLS.
- **L'app** : une session ne s'ouvre que par une passkey (WebAuthn, Face ID). La première
  s'inscrit avec un code à usage unique (`hub auth bootstrap-code`) ; une seconde passkey sert
  de secours. Le cookie de session n'est gardé en base que par son empreinte.
- **Les programmes** (assistant, collecteurs, Claude) : un jeton à portée et à date de fin
  ([D-017](decisions.md)). Le jeton n'est montré qu'une fois et gardé par son empreinte ; un
  jeton fini est refusé, une alerte prévient 14 jours avant, `hub token rotate` le renouvelle.
  Portées : `<domaine>:read`, `<domaine>:aggregates`, `<domaine>:propose`, `core:collector` ;
  la portée `app` n'existe que par une session passkey.

## Ce qu'un programme peut faire

- **Lire** : un jeton `…:aggregates` (celui de Claude) ne voit que des totaux, jamais une
  écriture ; une catégorie ou un mois de moins de 3 écritures est fondu ou masqué. Claude ne
  lit jamais les transactions individuelles.
- **Écrire** : jamais directement. Un outil de l'assistant crée une proposition ; l'effet
  n'a lieu qu'après validation dans l'app, un Face ID par lot, sur un défi qui porte
  l'empreinte du lot (le Double Sas, voir [architecture.md](architecture.md)). Une proposition
  qui a changé entre l'aperçu et la validation revient avec une nouvelle révision.
- **Texte de tiers** : un libellé bancaire est une donnée, jamais une instruction ; les
  réponses de l'assistant qui en contiennent le disent (`external_text`).

## Secrets

- Une clé age par instance (0400, sur le disque chiffré). `secrets.enc.yaml` est chiffré vers
  elle ; l'API chiffre un secret à la saisie et ne le relit jamais.
- Les originaux importés sont archivés chiffrés (`archive/<domaine>/`).
- Le kit de secours (clé et `secrets.enc.yaml` hors de la machine) :
  [exploitation/kit-de-secours.md](exploitation/kit-de-secours.md).

## Intégrité

- Tables protégées en ajout seul : triggers anti `UPDATE` et `DELETE`, `INSERT OR REPLACE`
  interdit. `hub verify` contrôle les triggers.
- Journal chaîné : chaque ligne protégée a son empreinte versionnée et chaque maillon porte le
  précédent ; `hub verify` rejoue la chaîne chaque nuit.
- Une base se reconstruit par rejeu depuis l'archive et se compare à l'originale
  (`hub finance rebuild`, `hub finance compare`).

## Journaux et dépôt

- Les journaux n'ont jamais de montant, libellé, IBAN, solde ni contrepartie : le filtre de
  `hub.platform.logging` retire ces clés, un test le vérifie.
- Aucune donnée réelle dans le dépôt, la CI ni les tests : des données fictives générées par du
  code (`scripts/demo_data.py`). `scripts/check_no_data.sh` et gitleaks le vérifient.
- Montants en entiers (centimes) avec leur devise, jamais de flottant.

## L'app web

- CSP stricte servie par Caddy : `default-src 'self'`, aucun script en ligne, aucune ressource
  extérieure, `frame-ancestors 'none'`.
- Les identifiants viennent du serveur : l'app n'en invente ni n'en dérive.

## Dépendances et images

- `pip-audit` et Dependabot sur les dépendances ; Trivy analyse les images publiées sur GHCR.
- Une image publiée ne se reconstruit pas ; `make deploy` vérifie sa version avant de
  l'utiliser, essaie la nouvelle version sur des données fictives et revient seul à la
  précédente au moindre échec ([exploitation/versions.md](exploitation/versions.md)).
