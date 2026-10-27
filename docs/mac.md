# Phase 1 : le hub sur le Mac, en conteneurs (L0-07, L0-08)

Jusqu'au lot de migration, tout tourne sur le Mac M1 Max dans des conteneurs Linux arm64.
Les mêmes images et le même `deploy/compose.yaml` serviront sur le Pi 5.

## 1. Une fois

1. **Moteur de conteneurs.** OrbStack (recommandé) ou Colima ; Docker Desktop fonctionne aussi.
   Tout ce qui suit n'utilise que `docker` et `docker compose`.
2. **FileVault** actif (Réglages Système → Confidentialité et sécurité). Le disque de la VM
   des conteneurs est alors sur le volume chiffré. Note la clé de secours dans le kit.
3. **Pas de veille sur secteur :** `sudo pmset -c sleep 0`. Capot fermé sans écran, le hub est
   injoignable : c'est accepté en phase 1.
4. **Outils :** `brew install age gitleaks`.
5. **Clé age de la machine** (seul secret en clair sur le Mac) :
   ```
   mkdir -p ~/.config/hub && age-keygen -o ~/.config/hub/age.key && chmod 400 ~/.config/hub/age.key
   ```
   La ligne `Public key: age1…` affichée sert à chiffrer ; `age-keygen -y ~/.config/hub/age.key` la réaffiche.
6. **Secrets chiffrés** (jamais de fichier en clair sur le disque) :
   ```
   printf 'restic:\n  password: "%s"\n' "$(openssl rand -base64 32)" \
     | age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/secrets.enc.yaml
   ```
   (`age-keygen -y` relit la clé publique depuis la clé de l'étape 5.)
   Copie le mot de passe restic dans le kit de secours avant de fermer le terminal :
   `age -d -i ~/.config/hub/age.key ~/.config/hub/secrets.enc.yaml`.
7. **Dossiers :** `mkdir -p ~/PersonalHub/inbox`, et sur le disque externe
   `/Volumes/<disque>/litestream` et `/Volumes/<disque>/restic`.
8. **Tailscale :** dans la console, ajoute le tag `tag:hub` (ACL de la spécification, section
   10) et crée une clé d'authentification à usage unique, étiquetée `tag:hub`.
9. **Réglages :** `cp deploy/.env.example deploy/.env`, puis remplis les chemins et
   `TS_AUTHKEY`. `HUB_PUBLIC_ORIGIN` se connaît après le premier démarrage (nom MagicDNS du
   nœud `hub`) ; les passkeys en dépendent, donc on la fixe avant d'inscrire la première.

## 2. Déployer

```
make deploy TAG=v0.1.0
```

`deploy/mac-preflight.sh` vérifie d'abord FileVault, la veille, la clé, les dossiers et
l'absence de port publié. Puis `deploy/deploy.sh` : construction des images, `hub verify`,
copie des bases, migrations, second `verify`, démarrage et contrôle de `/api/health` dans les
30 s. Au moindre échec après la copie, il restaure les bases et revient à l'image précédente.

Après le premier démarrage réussi, vide `TS_AUTHKEY` dans `deploy/.env` : l'état du nœud est
gardé dans le volume `ts-state`.

## 3. Première passkey

```
HUB_TAG=$(cat deploy/.current-tag) docker compose --env-file deploy/.env -f deploy/compose.yaml \
  run --rm --no-deps scheduler hub auth bootstrap-code
```

Sur l'iPhone (Tailscale actif), ouvre `HUB_PUBLIC_ORIGIN`, saisis le code, valide par
Face ID, puis ajoute tout de suite une **passkey de secours** (clé matérielle ou autre
appareil) depuis la page d'état. Partager → « Sur l'écran d'accueil » installe l'app.

## 4. Critères d'acceptation à cocher

- [ ] `/api/health` répond depuis le téléphone par Tailscale.
- [ ] Depuis un autre appareil du Wi-Fi, hors Tailscale, rien ne répond
      (`curl -m 3 http://<ip-du-mac>:8080` et `:8710` échouent).
- [ ] `docker volume ls` montre `hub_data` ; aucune `.db` dans un dossier du Mac.
- [ ] Connexion depuis Safari sur l'iPhone ; deux passkeys listées ; session expirée après 12 h.
- [ ] `make restore-test` : restauration depuis la réplique Litestream dans un projet vierge.
- [ ] Un déploiement raté revient seul à l'image précédente (essai :
      `HUB_STRICT_TAILSCALE=1` avec Tailscale arrêté).

## 5. Commandes utiles

Une commande à la main doit viser l'image déployée : `deploy/.current-tag` la retient
(sans elle, compose cherche `hub:dev` et échoue en « pull access denied »).

Les bases ne s'ouvrent jamais depuis macOS ; toute commande passe par un conteneur jetable :

```
alias hubc='HUB_TAG=$(cat deploy/.current-tag) docker compose --env-file deploy/.env -f deploy/compose.yaml'
hubc run --rm --no-deps scheduler hub token create brain-mac -s brain
hubc run --rm --no-deps scheduler hub verify
hubc logs -f api
```

## Risque assumé de la phase 1

Les données vivent sur la machine de tous les jours. Une session macOS compromise peut piloter
Docker, donc lire les bases ; les conteneurs protègent le hub contre ses propres composants,
pas contre ta session. D'ici la migration vers le Pi : FileVault actif, aucune donnée réelle
avant L1-11 ([docs/finance.md](finance.md)), prototype claude.ai supprimé au lot 4.
