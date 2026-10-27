# Collecteurs (lot 5) : BCF, VIAC et Revolut

Trois conteneurs déposent les exports officiels dans `~/PersonalHub/inbox/`, où l'importeur les
traite comme un fichier déposé à la main. Ils tournent sur le Mac comme le reste (phase 1) ; les
mêmes images et le même `deploy/compose.yaml` serviront sur le Pi.

| Collecteur | Comment | Quand (heure de Zurich) | Ce qu'il dépose |
|---|---|---|---|
| `collector-bcf` | navigateur sans tête, connexion avec validation push dans l'app BCF | 07:30 du lundi au vendredi | export camt.053 depuis J-10, « déjà téléchargées » coché |
| `collector-viac` | navigateur sans tête, profil gardé dans son volume | dimanche 09:00 | avis PDF nouveaux de la liste Documents, et un rapport tous les 6 jours |
| `collector-revolut` | API Enable Banking (PSD2), sans navigateur | 07:15, 13:15, 19:15 | un `revolut-<empreinte>.json` par compte, seulement s'il a changé |

Ce qu'un collecteur voit : la boîte d'entrée, son propre volume (profil du navigateur, mémoire
de ce qu'il a déjà déposé) et son propre fichier de secrets. Il ne lit jamais les bases et ne
remonte au hub que l'issue de chaque passage (`ok`, `nothing_new`, `auth_error`…), le nombre de
fichiers et une étape ou un nom de sélecteur, jamais un montant ni un texte de page. Un fichier
qui n'a pas la forme attendue (camt.053 ou zip de camt.053, PDF complet, JSON `hub.revolut.v1`)
part dans `inbox/quarantine/` au lieu d'être déposé.

## Quand ça casse

La table des échecs de la spécification (section 8) est appliquée par le hub :

| Issue | Effet |
|---|---|
| `ok`, `nothing_new` | remet le compteur à zéro |
| `auth_pending_timeout` (push ou lien non validé à temps) | alerte une fois par jour, jamais de suspension |
| `site_unavailable` | alerte au 3e de suite |
| `selector_missing`, `invalid_file`, `unknown` | alerte ; suspendu (« dégradé ») au 2e de suite |
| `auth_error` (refus, session VIAC expirée, consentement Revolut fini) | suspendu tout de suite, alerte urgente |

Un collecteur suspendu ne tourne plus à l'heure prévue. Dans l'app, onglet **Sources**, carte
**Collecteurs** : « Contrôler » demande un passage de contrôle (connexion et sélecteurs, sans
téléchargement) que le conteneur lance dans la minute ; s'il réussit, « Réactiver » apparaît.
« Désactiver » arrête un collecteur actif. Le retour à l'état actif reste toujours manuel.

Les alertes passent par ntfy, avec des textes génériques (« Collecte BCF : action requise »).
Le sujet ntfy vaut un mot de passe : il vit dans `secrets.enc.yaml`, section `ntfy`.

Pour comprendre un sélecteur manquant : `hubc run --rm collector-bcf hub-collector run bcf
--diagnose` garde des captures d'écran dans le volume du collecteur (purgées après 7 jours).
Si la banque a changé sa page, seul `hub/collectors/<banque>/selectors.toml` est à adapter.

## Mise en place (une fois)

Les commandes supposent l'alias `hubc` de [mac.md](mac.md) et partent du clone du dépôt
(`~/personal-hub/personal-hub`).

1. **Sujet ntfy.** Installe ntfy sur le téléphone, choisis un sujet long et aléatoire
   (`openssl rand -hex 16`), abonne-toi, puis ajoute-le au fichier de secrets principal :
   ```
   { age -d -i ~/.config/hub/age.key ~/.config/hub/secrets.enc.yaml; \
     printf 'ntfy:\n  topic: "%s"\n' "<ton-sujet>"; } \
     | age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/secrets.enc.yaml.new \
     && mv ~/.config/hub/secrets.enc.yaml.new ~/.config/hub/secrets.enc.yaml
   ```
2. **Un jeton par collecteur** (affiché une seule fois) :
   ```
   hubc run --rm --no-deps scheduler hub token create collector-bcf -s collector
   hubc run --rm --no-deps scheduler hub token create collector-viac -s collector
   hubc run --rm --no-deps scheduler hub token create collector-revolut -s collector
   ```
3. **Un fichier de secrets par collecteur**, dans `~/.config/hub/collectors/` (le chemin est
   `HUB_COLLECTOR_SECRETS` dans `deploy/.env`). Chaque fichier ne contient que sa section.
   Tape les valeurs dans un éditeur dont la sortie va directement à `age`, jamais dans un
   fichier en clair :
   ```
   mkdir -p ~/.config/hub/collectors && chmod 700 ~/.config/hub/collectors
   age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/collectors/bcf.enc.yaml
   ```
   puis colle, et termine par Ctrl-D :
   ```yaml
   collector-bcf:
     token: "hub_…"            # jeton de l'étape 2
     contract: "…"             # numéro de contrat e-banking
     password: "…"
   ```
   De même pour `viac.enc.yaml` (`collector-viac:` avec `token`, `email`, `password`) et
   `revolut.enc.yaml` (`collector-revolut:` avec `token`, `application_id`, `private_key`, voir
   plus bas).
4. **Déployer** avec la nouvelle image : `make deploy TAG=v0.5.0`. Les collecteurs ne
   démarrent pas encore.
5. **Premiers passages, un par un**, en regardant le téléphone :
   ```
   hubc run --rm collector-bcf hub-collector run bcf          # valide le push BCF
   hubc run --rm -it collector-viac hub-collector relogin viac # tape le code 2FA reçu
   ```
   Pour Revolut, voir la section suivante.
6. **Laisser tourner** : décommente `COMPOSE_PROFILES=collectors` dans `deploy/.env`, puis
   `hubc up -d`. À partir de là, `make deploy` met aussi les collecteurs à jour.

**VIAC : reconnexion.** La session VIAC finit par expirer ; le collecteur passe alors en
`auth_error` et tu reçois une alerte. Arrête-le, reconnecte-le, relance-le :
```
hubc stop collector-viac
hubc run --rm -it collector-viac hub-collector relogin viac
hubc up -d collector-viac
```
`relogin` remplit identifiant et mot de passe depuis les secrets, demande le code 2FA dans le
terminal, puis lance un contrôle ; il reste à cliquer « Réactiver » dans l'app. (La
spécification prévoyait un navigateur visible sur le Mac dont on copie le profil : un profil
Chromium de macOS ne se déchiffre pas sous Linux, d'où le code tapé dans le conteneur.)

## Revolut par Enable Banking

Enable Banking est le seul agrégateur PSD2 ouvert aux particuliers ; son mode « production
restreinte » est gratuit et ne lie que tes propres comptes. Chaque consentement dure au plus
180 jours. Revolut ne donne tout l'historique que dans les 5 minutes qui suivent un
consentement (90 jours ensuite) : la liaison lance la reprise complète dans la foulée.

**Test de liaison (15 min).**

1. Sur <https://enablebanking.com/cp/applications>, crée une application en production
   restreinte. Laisse le panneau générer la paire de clés et télécharge la clé privée (`.pem`).
   URL de redirection autorisée : `https://hub.<ton-tailnet>.ts.net/api/collectors/revolut/callback`
   (la même origine que `HUB_PUBLIC_ORIGIN`). Note l'identifiant de l'application.
2. Crée `revolut.enc.yaml` comme à l'étape 3, avec `application_id` et la clé :
   ```yaml
   collector-revolut:
     token: "hub_…"
     application_id: "…"
     private_key: |
       -----BEGIN PRIVATE KEY-----
       …
       -----END PRIVATE KEY-----
   ```
   puis efface le `.pem` téléchargé.
3. Vérifie que Revolut est proposé, et sous quel pays :
   ```
   hubc run --rm collector-revolut hub-collector revolut aspsps --country LT
   hubc run --rm collector-revolut hub-collector revolut aspsps --country CH
   ```
   Si Revolut n'apparaît que sous un autre pays que la Lituanie, mets-le dans
   `deploy/settings.toml`, `[collectors.revolut]`, `aspsp_country = "…"`.
4. Lie le compte, sur le Mac connecté au tailnet :
   ```
   hubc run --rm -it collector-revolut hub-collector revolut link
   ```
   Ouvre le lien affiché sur le téléphone (Tailscale actif), valide dans l'app Revolut. Le
   retour arrive sur le hub, le collecteur crée la session et dépose tout l'historique. La
   sortie liste les comptes vus (type, devise, produit) : c'est la réponse à la question
   « les pockets sont-elles des comptes séparés ? ».
5. Ouvre les comptes côté Finance. Les fichiers attendent tant que le compte n'existe pas :
   ```
   fin revolut pending                          # comptes en attente, sans montant
   fin revolut add-account revolut:CHF --name "Revolut CHF"
   ```
   `add-account` crée le compte, l'ouvre au solde déduit du fichier (solde annoncé moins les
   écritures, la veille de la première) et rejoue les imports en attente. Les autres comptes
   s'appellent `revolut:<DEVISE>:<produit>` (par exemple `revolut:EUR:savings`).
6. `hub-collector revolut status` donne les jours de consentement restants ; 14 jours avant, une alerte ntfy
   rappelle de relancer `revolut link`.

**Si Enable Banking ne convient pas : CSV.** Dans l'app Revolut, Relevé → Excel/CSV, puis
dépose le fichier dans `~/PersonalHub/inbox/`. Seules les lignes `COMPLETED` comptent, frais
déduits ; chaque ligne est vérifiée contre la colonne de solde. Un recouvrement avec un fichier
Enable Banking est reconnu (`near_duplicate`) et n'écrit rien deux fois. Les placements (actions,
crypto) ne passent pas par PSD2 : ils viendront au lot 6.
