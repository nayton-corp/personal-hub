# IA locale

Depuis S10, l'IA locale n'est plus un conteneur : c'est l'assistant ([assistant/](../assistant/README.md),
venu de Domia), qui tourne **en natif sur le Mac**, lancé par launchd, avec le modèle (Ollama, GPU) à
côté. Il joint le hub par Tailscale comme tes autres appareils, avec ses propres jetons, et ne touche à
aucune base. Rien ne sort du Mac.

```
téléphone ──► hub (api, conteneurs) ◄── Tailscale ── assistant (Mac, launchd) ──► Ollama (GPU)
                                                         ▲
                                     Domia (/api/talk) ──┘  voix et texte du foyer
```

Le code du hub qui parle à l'IA (`hub.brain` : client des routes d'outils, boîte à outils, classement,
passerelle MCP) reste une bibliothèque du hub ; l'assistant l'installe à côté de lui
(`pip install -e ..`) et s'en sert.

## Ce qu'il fait

- **Assistant** : à la voix ou par écrit, depuis l'app Domia, l'assistant reprend les outils des
  domaines du hub (`hub_capabilities`) **pour toi seul** (`hub.owners`) et avec le jeton des
  agrégats : Kim et les invités gardent la maison, sans aucun outil du hub. Les chiffres viennent
  toujours des outils.
- **Passerelle MCP** : `python -m domia_assistant mcp --person <toi>` expose les mêmes outils à un
  client MCP sur stdio (`hub-brain mcp --token aggregates` reste possible à la main).
- **Suggestions de catégorie**, chaque matin à 8 h 30 (`hub.classify_at`), par l'assistant et son
  modèle résident (un seul modèle chargé) : pour un commerçant qui n'a encore aucune
  écriture catégorisée, le modèle choisit une catégorie de la liste et donne sa raison en une
  ligne. Chaque écriture devient une carte « À valider » dans l'app, avec la raison. Une écriture
  n'est suggérée qu'une fois : une carte refusée ne revient pas.
- **Sentinelles** (dans le hub, pas dans le brain, sans modèle) : chaque nuit, budget dépassé ou
  qui va l'être, abonnement en hausse, marge 3a pas encore versée en novembre et décembre. Elles
  apparaissent dans « À traiter » et arrivent par ntfy avec un texte générique (ni montant, ni nom
  de commerçant). Toucher l'alerte ouvre l'app sur l'écran concerné (`/#alert=<id>`, un
  identifiant opaque : l'URL ne dit rien de l'alerte).

## Deux jetons

| Jeton | Portées | Pour | Voit |
|---|---|---|---|
| `brain` | `finance:read finance:propose` | le classement du matin (modèle local) | les 16 outils : totaux, écritures, recherche, propositions |
| `aggregates` | `*:aggregates` | la conversation de l'assistant, un client MCP | 7 outils de totaux, jamais une écriture |

Avec le jeton `aggregates`, une catégorie ou un mois qui compte moins de 3 écritures est fondu
dans « autres » ou masqué : un total ne révèle pas une transaction. Aucun outil ne renvoie
d'IBAN. Aucun outil ne peut appliquer quoi que ce soit : une proposition est une carte, qui ne
s'applique qu'avec ton Face ID. Un jeton crée au plus 60 propositions par heure.

## Le modèle

Un seul modèle de conversation reste chargé : celui de l'assistant (`model.name` de
`assistant/config.yaml`, Mistral Small 3.2 par défaut, choisi par le banc de Domia). Le classement
du matin s'en sert aussi : plus de second gros modèle qui chasserait le premier de la mémoire.

## Mise en place (une fois)

1. **L'assistant** : son installation, Ollama et son modèle compris :
   [assistant/README.md](../assistant/README.md). Dans son venv, le paquet du hub :
   `.venv/bin/pip install -e ..`.
2. **Deux jetons** (affichés une seule fois, chacun avec sa date de fin : 90 jours par défaut,
   `--days` jusqu'à 366), depuis le clone du dépôt avec l'alias `hubc` de
   [mac.md](exploitation/mac.md) :
   ```
   hubc run --rm --no-deps scheduler hub token create brain-mac -s brain=finance --days 180
   hubc run --rm --no-deps scheduler hub token create assistant-aggregates -s aggregates --days 180
   ```
   Quatorze jours avant la fin, ntfy prévient ; `hub token rotate ID` donne un nouveau secret
   (mêmes portées, l'ancien révoqué) à remettre dans `brain.enc.yaml`.
3. **Le fichier de secrets**, chiffré par age :
   ```
   age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/brain.enc.yaml
   ```
   puis colle, et termine par Ctrl-D :
   ```yaml
   brain:
     brain: "hub_…"          # jeton brain-mac (le classement)
     aggregates: "hub_…"     # jeton assistant-aggregates (la conversation)
   ```
4. **La section `hub:`** de `assistant/config.yaml` (modèle dans `config.example.yaml`) : l'adresse
   du hub par Tailscale, `owners` (ton identifiant de personne dans Domia), `secrets` et `age_key`.
   Relance l'assistant : `launchctl kickstart -k gui/$(id -u)/ch.domia.assistant`.
5. **Contrôle** : `.venv/bin/python -m domia_assistant check` dit si le hub répond et quels
   domaines il ouvre ; `classify --dry-run` montre les suggestions sans créer de carte.

## Au quotidien

Dans `~/personal-hub/personal-hub/assistant` :

```
.venv/bin/python -m domia_assistant classify --dry-run              # voir les suggestions
.venv/bin/python -m domia_assistant classify                        # créer les cartes maintenant
.venv/bin/python -m domia_assistant classify --mode catchup         # rattrapage : une règle par commerçant
.venv/bin/python -m domia_assistant classify --mode direct          # achats uniques : une carte par catégorie
```

`catchup` sert à vider une longue file « À classer » : une règle par commerçant (le motif est le
nom du groupe, le sens celui du groupe), qui classe le passé et les imports suivants. Un
commerçant déjà proposé ne revient pas ; relance-le une heure plus tard pour les 50 suivants
(60 propositions par heure et par jeton, `HUB_PROPOSALS_PER_HOUR` dans `deploy/.env`).

`direct` finit la file quand il n'y reste que des achats uniques : le modèle choisit une
catégorie par commerçant, puis une carte par catégorie réunit les écritures (30 au plus). Dans
« À valider », « Voir les écritures » déplie la carte : décoche celles qui ne vont pas, le reste
se valide du même Face ID.

Le Mac éteint ou Ollama arrêté, le passage de 8 h 30 échoue sans rien casser ; il reprend le
lendemain.

## Claude Desktop, en agrégats seulement (facultatif)

```json
{
  "mcpServers": {
    "personal-hub": {
      "command": "/Users/<compte>/personal-hub/personal-hub/assistant/.venv/bin/python",
      "args": ["-m", "domia_assistant", "mcp", "--person", "<toi>"],
      "env": {"PYTHONPATH": "/Users/<compte>/personal-hub/personal-hub/assistant"}
    }
  }
}
```

Claude ne voit du hub que les outils de totaux (le jeton des agrégats). Le jeton se révoque à
tout moment : `hubc run --rm --no-deps scheduler hub token revoke <id>`.

## Ce qui n'est pas encore là

- Le résumé hebdomadaire écrit par le modèle : il lui faut un endroit où être lu dans l'app ;
  ntfy ne transporte aucun chiffre.
- La sentinelle « garantie qui expire » arrivera avec le domaine Documents.
