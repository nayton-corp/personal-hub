# L'assistant de maison

Un service Python sur la machine IA du foyer (aujourd'hui le Mac M1 Max, plus tard une machine dédiée), client de
l'API de Domia comme tout appareil autorisé. La spec, dans le dépôt de Domia : `docs/superpowers/specs/2026-10-24-domia-assistant-design.md`.

Venu du dépôt de Domia au chantier S10 du hub ([D-021](../docs/decisions.md)) : un paquet à part, qui marche avec Domia
seul ; le contrat avec l'API de Domia est figé dans `domia_assistant/contract/` (`make domia-contract`).

- **Jamais dans la loop ni dans l'arbitre de Domia.** Le Mac éteint : plus de voix, la maison inchangée.
- **Les gestes de Domia, rien d'autre**, par le jeton de l'appareil autorisé « Assistant de maison », au nom de la
  personne qui parle ; ses initiatives sont des remarques, jamais des gestes.
- **Tout reste à la maison** : modèles, documents, mémoire sur le Mac. Seule une recherche web sort, si on l'active,
  avec la question seulement.

```
iPhone / app Domia ──POST /api/talk──▶ Domia (Pi) ──POST /talk──▶ assistant (Mac, :8770)
                                                                    ├─ voie rapide (grammaire, sans modèle)
                                                                    ├─ modèle local (Ollama / LM Studio, :11434)
                                                                    ├─ outils ──▶ API de Domia (gestes, lectures)
                                                                    ├─ bibliothèque, mémoire (~/Domia)
                                                                    └─ pont Rappels/Calendrier (:8771, EventKit)
```

| Dossier | Ce qu'il contient |
|---|---|
| `domia_assistant/grammar.py` | la voie rapide : la maison et les synonymes appris → des gestes du catalogue |
| `domia_assistant/assistant.py` | la conversation : voie rapide, sinon le modèle et ses outils ; le « oui » avant un geste pour toute la maison |
| `domia_assistant/tools.py` | les outils, dont les gestes générés de `GET /api/commands/catalog` (jamais `Toggle`) |
| `domia_assistant/reading.py` | savoir la maison : des lectures ciblées (pièce, sorte, objet, période), le journal en agrégats, les réglages en index puis en fiche, et le plafond d'une réponse (`fit`) |
| `domia_assistant/settings.py` | régler avec un oui : les changements typés sur une copie de la config, le résumé en unités de l'écran, la vérification par Domia, l'écriture après le oui (`If-Match`) et l'annulation |
| `parity/coverage.yaml` | rien d'impossible : pour chaque route de Domia, l'outil qui la sert, le lot qui l'apportera, ou pourquoi elle reste à l'écran |
| `domia_assistant/library.py` | `~/Domia/Bibliothèque/` : fiches des objets, documents indexés, entretien dû |
| `domia_assistant/memory.py` | `~/Domia/assistant.sqlite` : notes, synonymes, conversations (90 jours), refus |
| `domia_assistant/observer.py` | une remarque par heure au plus, jamais la nuit ni pendant la TV ; le brief du soir |
| `domia_assistant/mcp_server.py` | les mêmes outils au protocole MCP (Claude Desktop pour le banc) |
| `eventkit/` | le pont Rappels/Calendrier, séparé : le seul morceau attaché à Apple |
| `bench/` | les cas du banc (`cases.yaml`), leurs autres façons d'être dits (`variants.yaml`) et `run.py` |

## Installer sur le Mac

1. **Python et le code.** `brew install python@3.12`, puis dans `~/personal-hub/personal-hub/assistant` :
   `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r eventkit/requirements.txt`.
2. **Le serveur de modèle.** [Ollama](https://ollama.com) (ou LM Studio), puis les modèles du banc :
   `ollama pull mistral-small3.2:24b`, `ollama pull qwen3:30b-a3b`, `ollama pull gemma3:27b` (vision), `ollama pull bge-m3`
   (embeddings). Garder Ollama lancé. Puis le modèle de l'assistant, Mistral avec un gabarit qui garde les outils en
   cache (sans lui, chaque question recalcule ~3 000 jetons : 20 à 40 s de plus) :
   `ollama create domia-mistral -f ollama/domia-mistral.Modelfile`, et `model.name: domia-mistral` dans la config.
   Rien à régler pour qu'Ollama garde le modèle chargé : l'assistant l'envoie à chaque appel (`model.keep_alive`,
   24 h par défaut) et le prépare dès son démarrage, même après un redémarrage du Mac. Garder Ollama ouvert à la
   connexion (son réglage par défaut).
3. **L'appareil autorisé.** Dans Domia, Réglages → API → Appareils autorisés : « Autoriser un
   appareil » (nom : « Assistant »), copier le jeton, puis Modifier → Sorte : « L'assistant de maison ». Dans
   `assistant/.env` : `DOMIA_ASSISTANT_TOKEN=<jeton>`. Les téléphones qui parlent à l'assistant : leur appareil
   autorisé avec « Tenu par » la bonne personne. Pour que l'assistant écrive un réglage après un oui, le mot de passe
   de la configuration (celui du `htpasswd` du Pi) : `DOMIA_CONFIG_PASSWORD=<mot de passe>` (et `DOMIA_CONFIG_USER`,
   `client0` par défaut). Sans lui, il propose et Domia vérifie, mais Nginx refuse l'écriture (401).
4. **La config.** `cp config.example.yaml config.yaml` et ajuster (l'adresse du Pi, le modèle, `allow_from`).
5. **Domia sait où est l'assistant.** Sur le Pi, dans `/opt/domia-instance/.env` :
   `DOMIA_ASSISTANT_URL=http://<ip du Mac>:8770`, puis recréer le backend pour qu'il relise le `.env` (`deploy.sh`
   sur le tag déjà en place ne fait rien) : `docker compose -p domia-prod --env-file /opt/domia-instance/.env -f
   compose.prod.yml up -d domia-backend`. Sans cette ligne, `POST /api/talk` répond 503 et l'Accueil ne montre pas
   « Dis à l'appart ». Une réservation DHCP pour le Mac évite que l'adresse change.
6. **Rappels et Calendrier.** macOS donne l'accès à l'app responsable du programme qui le demande : lancé par
   launchd, le Python du venv n'en a pas et n'obtient rien. Le pont tourne donc dans une petite app :
   `sh eventkit/make-app.sh` crée `~/Applications/Domia Rappels.app` (ses phrases d'usage, signée localement), que le
   LaunchAgent ouvre. Au premier lancement, accepter les deux fenêtres de macOS (Rappels, Calendrier).
   `curl http://127.0.0.1:8771/health` doit dire `true` deux fois ; sinon Réglages Système → Confidentialité et
   sécurité → Rappels, puis Calendriers : autoriser « Domia Rappels ».
7. **Vérifier.** `.venv/bin/python -m domia_assistant check` : Domia, le modèle, la bibliothèque et le pont.
8. **Le Mac reste allumé** : Réglages Système → Économiseur d'énergie → empêcher la suspension automatique.

## Lancer avec launchd

Les deux services sont des LaunchAgents (ils tournent dans la session de l'utilisateur, avec ses autorisations) :

```sh
mkdir -p ~/Domia/logs ~/Applications
sh eventkit/make-app.sh
sed "s/COMPTE/$USER/g" launchd/ch.domia.assistant.plist > ~/Library/LaunchAgents/ch.domia.assistant.plist
sed "s/COMPTE/$USER/g" launchd/ch.domia.eventkit.plist > ~/Library/LaunchAgents/ch.domia.eventkit.plist
launchctl load ~/Library/LaunchAgents/ch.domia.eventkit.plist ~/Library/LaunchAgents/ch.domia.assistant.plist
tail -f ~/Domia/logs/assistant.log
```

Après une mise à jour de macOS, si `check` dit que le pont n'a pas l'accès : relancer l'étape 6.

## La recherche web

Quand la bibliothèque n'a rien (un code d'erreur absent du manuel, un manuel à retrouver), l'assistant cherche sur le
web par une instance [SearXNG](https://docs.searxng.org) sur le Mac, à l'écoute du Mac seul ; seule la question sort
(décision 5). Installer, puis `web_search_url: http://127.0.0.1:8888` dans `config.yaml` :

```sh
sh searxng/install.sh
sed "s/COMPTE/$USER/g" launchd/ch.domia.searxng.plist > ~/Library/LaunchAgents/ch.domia.searxng.plist
launchctl load ~/Library/LaunchAgents/ch.domia.searxng.plist
sleep 10; curl -s "http://127.0.0.1:8888/search?q=siemens+lave-vaisselle+E24&format=json" | head -c 300
launchctl kickstart -k gui/$(id -u)/ch.domia.assistant
```

## Préparer demain

À l'heure du brief (`brief_at`, 21 h par défaut), l'assistant compose le plan de demain sans modèle de langue (`planner.py`). Il prend l'agenda, la météo de Domia (`GET /api/weather`), les habitudes (`GET /api/memory/habits`), les constats et les rappels. Il fait au plus deux propositions :

- le robot pendant une absence ;
- fermer un volet avant la pluie ;
- un rappel au moment de partir.

Le premier « oui » qu'on lui dit ensuite les accepte, et « non » les refuse. Plus tard dans la conversation, le modèle s'en charge (`accept_planned`). « Qu'as-tu prévu ? » les liste ; « annule le robot » en retire un.

Un engagement accepté se joue au nom de la personne qui a dit oui, à son heure ou 15 min après le passage en Absent, et seulement si sa condition tient encore. Sinon, l'assistant ne joue rien et le dit une fois par une notification. Il expire à minuit le lendemain. Les engagements vivent dans `assistant.sqlite` : si le Mac est éteint au moment de jouer, l'engagement est perdu, et l'assistant le dit au tour suivant (au-delà de 30 min de retard, c'est trop tard).

## La voix

L'écran Assistant de Domia enregistre pendant l'appui long sur l'orbe et envoie le son à Domia, qui le relaie ici
(`POST /voice`). Le Mac le transcrit avec Whisper, joue la phrase comme une phrase tapée, puis dit la réponse avec la
synthèse de macOS. Rien ne sort de la maison, et le son n'est gardé nulle part (un fichier temporaire, effacé).

1. **Installer** : `brew install ffmpeg`, puis dans `~/personal-hub/personal-hub/assistant` : `.venv/bin/pip install mlx-whisper`.
2. **Vérifier** : `.venv/bin/python -m domia_assistant voice`. La première fois, cela télécharge le modèle Whisper
   (~1,6 Go), puis dit une phrase et la transcrit.
3. **Choisir la voix** (facultatif) : `say -v '?' | grep fr_` liste les voix françaises. Une voix « améliorée »
   (Amélie, Thomas) se télécharge dans Réglages Système → Accessibilité → Contenu énoncé → Voix du système. Ensuite,
   `assistant.say_voice: Amélie (amélioré)` dans la config, et relancer le service.

Le service ajoute lui-même `/opt/homebrew/bin` et `/usr/local/bin` à son PATH (un LaunchAgent démarre sans eux) :
le `ffmpeg` de Homebrew suffit, sans toucher au plist.

Sans mlx-whisper, `POST /voice` répond `VOICE_UNAVAILABLE` et l'écran le dit ; l'écrit marche toujours.
`assistant.voice: false` éteint la voix. Le micro de l'écran ne marche que par l'adresse https de Domia (Tailscale) :
le navigateur le refuse en http.

## Les outils du hub

Avec le paquet du hub installé à côté (`.venv/bin/pip install -e ..`) et une section `hub:` dans `config.yaml`,
l'assistant reprend les outils des domaines du hub (`hub_capabilities`) : un type de demande par domaine pour le
modèle en deux temps, et les consignes de chaque domaine dans son système. Trois règles, tenues par le code
(`domia_assistant/hub.py`) :

- **Au propriétaire seul.** Les outils du hub ne sont montrés et ne répondent qu'aux personnes de `hub.owners`.
  Kim, les invités et une voix de pièce gardent la maison ; même nommé par le modèle, un outil du hub n'existe pas
  pour eux.
- **Des agrégats.** Le jeton est celui des agrégats (`aggregates`) ; un domaine que le jeton lirait en entier est
  écarté, sauf s'il est nommé dans `hub.full_domains`. Une question d'argent n'obtient que des totaux.
- **Rien sans validation.** Un outil qui écrit crée une proposition, validée dans l'app du hub.

Le jeton vient du fichier de secrets chiffré du hub (`hub.secrets`, section `brain`, déchiffré avec `hub.age_key`) ;
`HUB_ASSISTANT_TOKEN` le remplace pour un essai. Un hub qui ne répond pas laisse la maison telle quelle et se
retente toutes les 5 minutes. `check` dit s'il répond et quels domaines il ouvre.

## La bibliothèque

`~/Domia/Bibliothèque/` : une fiche par objet (`lave-vaisselle.yaml`) et ses documents à côté, en sous-dossier
(`lave-vaisselle/manuel.pdf`), plus les documents du foyer (bail, assurances, décomptes). Les photos de plaques et les
e-mails de commande (`.eml`, PDF) se déposent dans `à-trier/` : l'assistant les lit (« regarde ce qu'il y a à
trier ») et crée les fiches. Après un ajout de documents : `python -m domia_assistant index`.

```yaml
# lave-vaisselle.yaml
name: Lave-vaisselle
room: Cuisine
brand: V-Zug
model: Adora 60 V4000
bought_at: 2024-03-12
shop: Galaxus
maintenance:
  - {what: nettoyer le filtre, every: 1 mois, last: 2026-10-01}
```

## Le banc d'essai

Avant tout usage quotidien, le modèle se choisit sur des chiffres (spec §13), contre l'essai, jamais contre la vraie
maison : `cp config.example.yaml config.essai.yaml` avec `domia.url: http://192.168.0.63:3001` et le jeton d'un
appareil autorisé ASSISTANT **de l'essai**, des manuels réels dans la bibliothèque, puis
`.venv/bin/python bench/run.py`. Le résultat va dans `bench/results/`. Erreurs graves (un geste non demandé) : zéro,
sinon le modèle est écarté. On change `model.name` et on recommence.

Chaque cas se joue sous plusieurs formulations (`variants.yaml`). `--set dev` (le cas et ses variantes) sert à
corriger, `--set control` (des phrases jamais regardées pour corriger) à vérifier, `--set all` (défaut) la nuit. Tout
changement du prompt, des descriptions d'outils ou de la réponse passe par le banc avant un essai dans la maison : la
réussite et les temps (médian, max) par famille ne baissent pas. Le banc partage le modèle de la maison : on ne parle
pas à l'assistant pendant qu'il tourne.

**La référence, Claude.** Dans Claude Desktop, Réglages → Développeur → Modifier la config, ajouter :

```json
{"mcpServers": {"domia-essai": {"command": "/Users/<compte>/personal-hub/personal-hub/assistant/.venv/bin/python",
  "args": ["-m", "domia_assistant", "mcp", "--config", "/Users/<compte>/personal-hub/personal-hub/assistant/config.essai.yaml", "--person", "alex"],
  "env": {"PYTHONPATH": "/Users/<compte>/personal-hub/personal-hub/assistant"}}}}
```

`PYTHONPATH` : le paquet n'est pas installé dans le venv, et Claude Desktop ne lance pas la commande depuis `assistant/`.

puis jouer les phrases de `bench/cases.yaml` à la main et noter les résultats à côté.

## Développer

```sh
pip install -r requirements-dev.txt && python -m pytest -q          # l'assistant, avec un faux Domia et un modèle scripté
python -m ruff check . && python -m ruff format --check . && python -m mypy   # ce que la CI exige aussi (ruff format . pour reformater)
cd eventkit && pip install -r requirements-dev.txt && python -m pytest -q   # le pont, avec un faux magasin
python -m domia_assistant say "éteins le salon" --person robin      # une phrase, sans passer par Domia
```
