# Glossaire

Les mots du hub, fixés une fois. Le code, les écrans et la documentation les reprennent tels
quels, en français. Un mot nouveau entre ici dans la même PR que le code qui l'introduit.

## Architecture

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Hub** | Une instance pour une personne : son API, ses bases, son app. | `hub` |
| **Instance** | Un hub installé, avec son profil et ses domaines actifs. | `hub init`, `HUB_DOMAINS` (à venir) |
| **Noyau** | Le code pur partagé par tous : argent en centimes, URN, horloge, JSON canonique. Ni base, ni réseau. | `hub.core.money`, `canonical`, `clock`, `ids`, `text` ; plus tard `hub.kernel` |
| **Plateforme** | La technique commune : SQLite, migrations, réglages, secrets, journaux, planificateur, sauvegarde. Elle ne connaît pas le métier. | `hub.core.db`, `coredb`, `settings`, `secrets`, `logging`, `cron` ; plus tard `hub.platform` |
| **Cœur** | Ce que tous les domaines partagent : identité et accès, validation (Double Sas), intégration (URN, liens, recherche), sources, profil. Il ne cite aucun domaine. | `hub.core` |
| **Domaine** | Un pan de la vie (finance, puis agenda, documents, maison). Sa base, ses migrations, ses outils, ses propositions. | `hub.domains.<nom>`, protocole `Domain` |
| **Manifeste** | Ce qu'un domaine déclare au cœur : sortes de propositions, outils, routes, tâches de nuit. | `hub.core.domain` |
| **Porte publique** | Le seul module qu'un autre domaine peut lire. | `hub.domains.<nom>.public` |
| **Bord** | Ce qui parle au monde : API HTTP, ligne de commande, app web, collecteurs, assistant. | `hub.api`, `hub.cli`, `hub/web`, `hub.collectors`, `hub.brain` |
| **Couches d'un domaine** | `model` (pur), `app` (cas d'usage), `infra` (SQL, fichiers), `interface` (routes, CLI, outils). Les dépendances descendent. | à venir (S6) |

## Validation

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Proposition** | Un changement demandé par un auteur (toi, l'assistant, un collecteur, une sentinelle). Elle ne s'applique qu'après sa validation. | `proposals` |
| **Carte** | Une proposition qui attend ta décision dans « À valider ». | palier `human` |
| **Double Sas** | Proposer, puis valider : rien ne change sans passer les deux. | `hub.core.proposals` |
| **Aperçu** | Ce que la proposition changera, calculé par le domaine et montré sur la carte. | `preview_json` |
| **Empreinte** | Le condensé de l'aperçu. Face ID la signe ; le cœur la revérifie avant d'appliquer. | `fingerprint` |
| **Palier** | Le traitement d'une proposition : `human` (carte), `auto_digest` (appliquée, puis reprise dans le résumé du jour), `auto` (appliquée sans rien dire). | `approval_policies`, `tier` |
| **Résumé du jour** | Les effets appliqués au palier `auto_digest`, chacun avec son inverse. | `digest` |
| **Lot** | Des propositions validées ensemble, d'un seul Face ID. | `bundle_id` |
| **Inverse** | La proposition qui annule un effet réversible. | lien `reverts` |
| **Effet externe** | Un changement chez un tiers (un virement, un geste vers Domia). Jamais automatique. | `ExternalHandler` |
| **Texte externe** | Un texte venu d'ailleurs (relevé, page, document). Une proposition qui en est tirée passe toujours par une carte. | `external_text` |

## Données

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Registre** | Le journal des écritures, en ajout seul, chaîné par empreintes et vérifié chaque nuit. | `ledger` |
| **Écriture** | Une ligne du registre : montant en centimes, devise, date, compte. | `entries` |
| **Ajout seul** | Une écriture n'est jamais modifiée ni supprimée (des triggers le refusent) ; son classement vit à côté, dans les catégorisations. | `categorizations` |
| **Relevé** | Un fichier d'une source (camt.053, CSV, rapport) importé en une fois. | `import_statements` |
| **Boîte d'entrée** | Le dossier où un collecteur dépose les fichiers d'un domaine. | `inbox/` |
| **Collecteur** | Un programme qui télécharge les exports officiels d'une source. Il ne touche jamais une base. | `hub.collectors` |
| **Connecteur** | Une sorte de source (BCF, VIAC, Enable Banking…), décrite au catalogue. | `hub.core.connectors` |
| **Connexion** | Un connecteur configuré pour une instance, avec ses secrets. | `connections` |
| **Règle** | Un motif qui classe les écritures, passées et à venir. | `rules` |
| **Pack** | Un ensemble de règles prêtes à installer. | `packs` |
| **Dérivé** | Ce qui se recalcule depuis le registre : virements appariés, récurrences, instantanés. | `rebuild`, `snapshots` |
| **Sentinelle** | Une vérification de nuit, sans modèle, qui lève une alerte (budget dépassé, abonnement en hausse). | `sentinels` |
| **Données fictives** | Un an de relevés inventés pour deux comptes, seules données des tests, de la CI et de l'instance d'essai. | `scripts/demo_data.py` |
| **Instance d'essai** | Un hub jetable où l'image d'une version migre les données fictives et répond, avant tout déploiement. | `deploy/trial.sh` |
| **Agrégat** | Un total qui ne révèle aucune transaction (moins de 3 écritures : fondu ou masqué). C'est tout ce que Claude voit. | portée `*:aggregates` |
| **URN** | L'identifiant stable d'un objet, d'un domaine à l'autre : `hub:<domaine>:<sorte>:<id>`. | `hub.core.ids` |
| **Lien** | Une relation entre deux URN, tenue par le cœur. | `links` |

## Accès et IA

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Jeton** | Un accès sans session, pour un programme. | `tokens` |
| **Portée** | Ce qu'un jeton peut faire : `<domaine>:read`, `:propose`, `:aggregates`. | `scopes` |
| **Brain** | L'IA locale du hub (Ollama sur le Mac), qui ne voit le hub que par l'API. Remplacé plus tard par l'assistant unique. | `hub.brain` |
| **Assistant** | La voix et la conversation du foyer, reprises de Domia (chantier S10). | à venir |
