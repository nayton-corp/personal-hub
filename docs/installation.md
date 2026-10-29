# Installer son hub

Un hub sert une seule personne : sa clé age, ses passkeys, ses bases. Pour un deuxième
utilisateur, on installe un deuxième hub. Rien de ce dépôt ne dépend d'une personne : les règles
de catégorisation viennent de packs neutres, les banques s'ajoutent depuis l'app, et le prénom,
le pays, la devise et le fuseau sont des réglages.

## Ce qu'il faut

- Une machine allumée en permanence, avec Docker. Un Mac (Docker Desktop ou OrbStack) est le
  cas éprouvé, et les réglages propres au Mac sont dans [mac.md](mac.md). Les images sont
  construites en `linux/arm64` ; pour une machine Intel ou AMD, mets `HUB_PLATFORM=linux/amd64`
  dans l'environnement avant `make init` et `make deploy`.
- Le disque chiffré (FileVault, LUKS…). Seule la clé age y vit en clair.
- Un compte Tailscale : l'app n'est joignable que par le tailnet, jamais depuis Internet.
- Un téléphone qui gère les passkeys (Face ID, empreinte), avec Tailscale.

## 1. Préparer la machine

```
git clone <ce dépôt> personal-hub && cd personal-hub
make init
```

`make init` construit l'image du hub et lance `hub init` dans un conteneur jetable : rien d'autre
que Docker n'est requis. Il demande, avec une valeur proposée à chaque fois :

| Question | Défaut | Remarque |
|---|---|---|
| Dossier de la clé et des secrets | `~/.config/hub` | hors de tout dossier synchronisé (iCloud, Dropbox) |
| Dossier des exports et des sauvegardes | `~/PersonalHub` | `inbox/`, `backup/litestream/`, `backup/restic/` |
| Fuseau | celui de la machine | jour civil des chiffres, horaires des collecteurs |
| Pays | `CH` | pack de règles de la base et modules du pays (pilier 3a en Suisse) |
| Devise de base | `CHF` | fixée à la création de la base, **ne change plus** |
| Adresse du hub | — | `https://hub.<tailnet>.ts.net`, voir la console Tailscale → DNS |

Il écrit ensuite la clé age (0400), `secrets.enc.yaml` (mot de passe restic tiré au hasard,
jamais affiché), les dossiers et `deploy/.env`. Relancé, il ne remplace rien : il complète ce
qui manque. Sans question, par variables : `HUB_CONFIG`, `HUB_HOME`, `HUB_TZ`, `HUB_COUNTRY`,
`HUB_CURRENCY`, `HUB_PUBLIC_ORIGIN`. `HUB_DOMAINS` (dans `deploy/.env`, `*` par défaut)
choisit les domaines montés.

**Kit de secours, tout de suite :** une copie de `age.key` et de `secrets.enc.yaml` hors de la
machine (clé USB au coffre, gestionnaire de mots de passe). La clé seule rouvre les secrets et
les sauvegardes restic ; sans elle, une sauvegarde est perdue. Le reste du kit :
[kit-de-secours.md](kit-de-secours.md).

## 2. Tailscale

Dans la console Tailscale, ajoute le tag `tag:hub` aux ACL et crée une clé d'authentification
à usage unique étiquetée `tag:hub`. Colle-la dans `deploy/.env` (`TS_AUTHKEY=`). Après le
premier démarrage, vide-la : l'état du nœud reste dans le volume `ts-state`.

## 3. Premier déploiement

```
make deploy TAG=v1
```

`make deploy` contrôle la machine (`deploy/mac-preflight.sh`), construit les images (ou tire
celles d'une version publiée, [versions.md](versions.md)), crée les
bases, démarre les services et attend `/api/health`. Au premier déploiement, il affiche à la fin
un **code d'inscription** valable quelques minutes. Sur le téléphone, ouvre l'adresse du hub,
saisis le code et valide par Face ID : c'est la première passkey. Le code a expiré ?

```
HUB_TAG=v1 docker compose --env-file deploy/.env -f deploy/compose.yaml \
  run --rm --no-deps scheduler hub auth bootstrap-code
```

Partager → « Sur l'écran d'accueil » installe l'app.

## 4. Premiers pas dans l'app

L'accueil affiche une carte **Premiers pas** tant qu'il reste quelque chose à faire :

1. **Passkey de secours** : une seconde clé (autre appareil, clé matérielle) si le téléphone se
   perd.
2. **Profil** : le prénom qu'emploie l'assistant, le pays.
3. **Règles de catégorisation** : une base neuve reçoit le pack `base` et celui de son pays.
   Si le pays a changé ensuite, « Installer » propose les packs du nouveau pays, validés par
   Face ID. Tes règles d'un autre hub : `fin rules export`, puis
   `fin rules packs install <fichier>` ([finance.md](finance.md)).
4. **Première connexion** : Sources → Connexions → « Ajouter ». Le catalogue couvre les banques
   européennes par Enable Banking, IBKR, les cours et portefeuilles crypto, des plateformes
   crypto, et deux robots suisses (BCF, VIAC). Les identifiants sont chiffrés à la saisie et ne
   se réaffichent jamais ([collectors.md](collectors.md)).
5. **Premier compte** : les relevés d'un compte inconnu attendent sa création, validée par
   Face ID dans Sources → Comptes. Un relevé camt.053, CSV ou PDF peut aussi être déposé à la
   main dans `inbox/`.

La carte disparaît quand tout est fait, ou avec « Masquer ».

## 5. Ensuite

- **Mettre à jour :** `git fetch --tags && git checkout vX.Y.Z && make deploy TAG=vX.Y.Z`. Les
  images d'une version publiée se tirent de GHCR ([versions.md](versions.md)) ; le déploiement
  les essaie sur des données fictives, copie les bases avant de migrer et revient seul à la
  version précédente au moindre échec.
- **Commandes à la main :** l'alias `hubc` de [mac.md](mac.md#5-commandes-utiles).
- **Alertes sur le téléphone** (ntfy) et **IA locale** : [brain.md](brain.md).
- **Sauvegardes :** la réplique Litestream et restic tournent seuls dans `backup/`. Une copie
  hors machine s'ajoute avec `repository_offsite` dans la section `restic` des secrets.

## Sur Linux

Les conteneurs tournent sous l'utilisateur 10001. Sur Docker Desktop et OrbStack (macOS), le
partage de fichiers s'en accommode ; sur Linux, donne-lui le dossier des secrets après
`make init` : `sudo chown -R 10001:10001 ~/.config/hub ~/PersonalHub`.
