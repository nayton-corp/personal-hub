# Vision

Un hub personnel, chez soi : un seul endroit où vivent les données de sa vie (argent, agenda,
documents, maison), tenues par du code qu'on lit, sur une machine qu'on possède, avec un
assistant qui aide sans jamais agir à sa place.

## Ce que le hub est

- **À soi.** Un hub par personne, auto-hébergé (le Mac aujourd'hui, un Raspberry Pi plus
  tard), joignable seulement par son tailnet. Aucune donnée ne part chez un tiers ; les
  sauvegardes sont chiffrées.
- **Fait de domaines.** La finance d'abord, puis l'agenda, les documents, la maison. Un
  domaine est un paquet Python et un module de l'app, branchés sans toucher au reste : le cœur
  (accès, propositions, trace, intégrité) est commun.
- **Digne de confiance.** Un registre en ajout seul, chaîné, qui se reconstruit depuis
  l'archive et se compare à lui-même. Des montants exacts, jamais arrondis. Des journaux
  sans contenu.
- **Proactif sans autonomie.** Le hub remarque (budget dépassé, consentement qui expire,
  document à renouveler) et propose ; la personne valide d'un Face ID. Rien ne s'écrit sans
  elle.

## Un seul assistant

L'assistant de Domia devient celui du hub : il lit les outils de chaque domaine
(`hub_capabilities`), répond à la voix comme par écrit, et ne voit de l'argent que des totaux.
Son modèle tourne sur la machine ; aucune question ne sort.

## Domia reste à part

Domia pilote les lampes de la maison au-dessus de Home Assistant : une boucle temps réel, un
foyer à plusieurs, une tablette. Elle reste un service à part, branché au hub par un domaine
« maison » ; Kim et la tablette n'ont jamais besoin du hub pour allumer une lampe.

## La règle pour ranger un usage

À part si c'est du temps réel, un outil qui existe déjà, ou un usage à plusieurs ; sinon un
domaine du hub. Par défaut, on intègre.

## L'ordre

1. **Le socle** : contrat de domaine, app modulaire, finance en couches, intégrité et boîte
   d'entrée génériques, exploitation sans liste en dur, documentation.
2. **La recherche, les liens et les constats** communs aux domaines.
3. **Un seul assistant**, venu de Domia.
4. **Agenda**, premier domaine réel monté sans toucher au cœur.
5. **Documents**, qui reprend la bibliothèque de Domia.

Le critère du socle tient en un test : ajouter un domaine, c'est un paquet Python et un module
d'app, sans modifier une ligne du cœur, de la finance ou de l'app
([docs/ajouter-un-domaine.md](docs/ajouter-un-domaine.md)).
