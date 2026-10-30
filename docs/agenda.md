# Agenda

Rappels et Calendrier du Mac, dans le hub : l'accueil montre la semaine, les rappels ouverts et
la liste de courses ; l'assistant les lit et propose d'y ajouter. Rien n'est copié : tout reste
dans Rappels et Calendrier, synchronisés par iCloud comme d'habitude.

## Ce qui passe par une carte

| Geste | Palier |
|---|---|
| ajouter un rappel, un événement | une carte à valider |
| cocher un rappel | une carte à valider |
| ajouter un article à la liste de courses (« Courses ») | automatique, sans carte |
| supprimer | jamais : ni le pont ni le hub ne le savent faire |

Un modèle (l'assistant) reste toujours à la carte, même pour les courses, tant qu'il ne déclare
pas que la demande ne vient pas d'un texte externe. Le palier se change :
`hubc run --rm --no-deps scheduler hub proposals policy agenda add_shopping human`
(`default` pour revenir au palier du type).

## Mise en place

1. **Le pont** tourne sur le Mac, dans une petite app qui a l'accès de macOS à Rappels et à
   Calendrier : [assistant/README.md](../assistant/README.md), « Rappels et Calendrier ».
   `curl http://127.0.0.1:8771/health` doit dire `true` deux fois.
2. **Le hub le joint** par `host.docker.internal:8771` (section `[agenda]` de
   `deploy/settings.toml`). `hubc run --rm --no-deps api hub agenda status` le vérifie.
3. Le domaine est monté avec les autres (`HUB_DOMAINS=*`) ; `HUB_DOMAINS=finance` l'éteint.

Le Mac en veille ou l'accès retiré, l'accueil dit « Rappels et Calendrier ne répondent pas pour
l'instant » ; le reste du hub continue.
