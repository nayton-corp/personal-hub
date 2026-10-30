# Glossaire

Les mots du hub, fixés une fois. Le code, les écrans et la documentation les reprennent tels
quels, en français. Un mot nouveau entre ici dans la même PR que le code qui l'introduit.

## Architecture

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Hub** | Une instance pour une personne : son API, ses bases, son app. | `hub` |
| **Instance** | Un hub installé, avec son profil et ses domaines actifs. | `hub init`, `HUB_DOMAINS` (à venir) |
| **Noyau** | Le code pur partagé par tous : argent en centimes, URN, horloge, JSON canonique. Ni base, ni réseau. | `hub.kernel` : `money`, `canonical`, `clock`, `ids`, `text` |
| **Plateforme** | La technique commune : SQLite, migrations, réglages, secrets, journaux, planificateur, sauvegarde. Elle ne connaît pas le métier. | `hub.platform` : `db`, `migrations`, `settings`, `secrets`, `logging`, `cron` |
| **Cœur** | Ce que tous les domaines partagent : identité et accès, validation (Double Sas), intégration (URN, liens, recherche), sources, profil. Il ne cite aucun domaine. | `hub.core` |
| **Domaine** | Un pan de la vie (finance, puis agenda, documents, maison). Sa base, ses migrations, ses outils, ses propositions. | `hub.domains.<nom>`, protocole `Domain` |
| **Contribution** | Ce qu'un domaine apporte au cœur sans que le cœur l'importe (connecteurs, modules par pays, reprise d'anciennes connexions), déclaré comme point d'entrée du paquet. | `hub.core.registry.contributions`, `[project.entry-points."hub.…"]` |
| **Manifeste** | Ce qu'un domaine déclare au cœur : onglets, cartes d'accueil et rubriques de l'app, fichiers qu'il réclame, connecteurs, tables protégées, consignes pour l'assistant ; avec ses sortes de propositions, outils, routes et tâches de nuit. | `hub.core.manifest`, `Domain.manifest()`, `GET /api/domains` |
| **Sous-contexte** | Une partie d'un domaine qui a son vocabulaire et ses couches (interface, app, infra, model) ; la finance en a quatre : registre, classement, patrimoine, sources. | `hub.domains.finance.<sous-contexte>` |
| **Lecture publique** | Ce qu'un domaine laisse lire aux autres, des agrégats seulement. | `hub.domains.<nom>.public` |
| **Constat** | Ce qu'un domaine remarque seul (budget dépassé, abonnement en hausse) : un titre sans montant, une gravité. | `Domain.observations()`, `Observation` |
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
| **Effet externe** | Un changement chez un tiers (un virement, un geste vers Domia, un rappel ajouté). Jamais automatique, sauf un article sur la liste de courses ([D-023](decisions.md)). | `ExternalHandler` |
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
| **Connecteur** | Une sorte de source (BCF, VIAC, Enable Banking…), décrite au catalogue que la finance déclare. | `hub.domains.finance.sources.app.connectors`, lu par `hub.core.connectors.catalog()` |
| **Connexion** | Un connecteur configuré pour une instance, avec ses secrets. | `connections` |
| **Règle** | Un motif qui classe les écritures, passées et à venir. | `rules` |
| **Pack** | Un ensemble de règles prêtes à installer. | `packs` |
| **Dérivé** | Ce qui se recalcule depuis le registre : virements appariés, récurrences, instantanés. | `rebuild`, `snapshots` |
| **Sentinelle** | Une vérification de nuit, sans modèle, qui lève une alerte (budget dépassé, abonnement en hausse). | `sentinels` |
| **Données fictives** | Un an de relevés inventés pour deux comptes, seules données des tests, de la CI et de l'instance d'essai. | `scripts/demo_data.py` |
| **Instance d'essai** | Un hub jetable où l'image d'une version migre les données fictives et répond, avant tout déploiement. | `deploy/trial.sh` |
| **Agrégat** | Un total qui ne révèle aucune transaction (moins de 3 écritures : fondu ou masqué). C'est tout ce que Claude voit. | portée `*:aggregates` |
| **URN** | L'identifiant stable d'un objet, d'un domaine à l'autre : `hub:<domaine>:<sorte>:<id>`. | `hub.kernel.ids` |
| **Lien** | Une relation entre deux URN, tenue par le cœur ; elle se crée par une carte (`core/link`) et se défait par son inverse. | `links`, `hub.core.links` |

## Accès et IA

| Mot | Sens | Dans le code |
| --- | --- | --- |
| **Jeton** | Un accès sans session, pour un programme, avec ses portées et sa date de fin (alerte 14 jours avant, `hub token rotate`). | `tokens`, `hub.core.tokens` |
| **Portée** | Ce qu'un jeton peut faire : `<domaine>:read`, `:propose`, `:aggregates`, `:household`. | `scopes` |
| **Foyer** (marque) | Un document lisible par tout le foyer, et pas seulement par les propriétaires ; sans marque, il est privé ([D-025](decisions.md)). | `marks`, `documents:household` |
| **Brain** | L'IA locale du hub (Ollama sur le Mac), qui ne voit le hub que par l'API. Remplacé plus tard par l'assistant unique. | `hub.brain` |
| **Assistant** | La voix et la conversation du foyer, reprises de Domia (chantier S10). | à venir |
