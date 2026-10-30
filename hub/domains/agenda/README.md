# Domaine Agenda (code)

Le premier domaine réel monté sans toucher au cœur ([D-024](../../../docs/decisions.md)) :
Rappels et Calendrier du Mac, lus et écrits par le pont EventKit
([assistant/eventkit/](../../../assistant/eventkit/)). L'usage : [docs/agenda.md](../../../docs/agenda.md).

| Module | Ce qu'il tient |
|---|---|
| `domain.py` | `AgendaDomain`, le contrat de domaine ; lectures au pont, recherche, constats, santé |
| `bridge.py` | le client du pont (`host.docker.internal:8771` par défaut) ; transport remplaçable |
| `kinds.py` | les types de proposition à effet externe : `add_reminder`, `add_event`, `complete_reminder`, `add_shopping` (palier `auto`) |
| `tools.py` | les outils de l'assistant : lire, compter, proposer |
| `api.py` | `/api/agenda/overview`, `/upcoming`, `/counts` ; `hub agenda status` |
| `migrations/` | `agenda.db` : journal commun et `sent` (les envois au pont) |

- **Aucune copie** : la base ne garde ni rappel ni événement, seulement la trace des envois
  (`sent` : clé d'idempotence, type, paramètres, issue, identifiant rendu par le pont).
- **Jamais de suppression** : le pont n'en a pas, le domaine non plus.
- **Idempotence** : un envoi est noté `sending` avant l'appel ; la même clé rejouée rend le
  premier résultat. Un appel au résultat inconnu (pont coupé en route) se réconcilie : la
  trace, sinon ce que le pont montre (même titre, même date).
- **Le pont absent** n'est pas une panne du hub : les routes et les outils rendent
  `available: false`, la santé du domaine ne dépend que de sa base.
