# IA locale (lot 7)

Le « brain » est un conteneur de plus, au profil compose `brain`. Il ne touche à aucune base : il
parle au hub par l'API, avec ses propres jetons, et au modèle, qui tourne **en natif sur le
Mac** pour avoir le GPU. Rien ne sort du Mac.

```
téléphone ──► hub (api) ◄── brain ──► Ollama (macOS, GPU)
                              ▲
              client MCP ─────┘  (docker exec -i, stdio)
```

## Ce qu'il fait

- **Passerelle MCP** : `hub-brain mcp` expose les outils du hub à un client MCP sur stdio. Elle
  commence par `hub_capabilities` (les domaines ouverts au jeton) et `hub_load_tools` (les outils
  d'un domaine, chargés à la demande ; d'emblée quand le jeton n'ouvre qu'un domaine).
- **Assistant** : `hub-brain ask "combien en restaurants ce mois ?"` pose la question au modèle
  local, qui appelle les outils et répond. Les chiffres viennent toujours des outils.
- **Suggestions de catégorie**, chaque matin à 8 h 30 : pour un commerçant qui n'a encore aucune
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
| `brain` | `finance:read finance:propose` | le modèle local | les 16 outils : totaux, écritures, recherche, propositions |
| `aggregates` | `*:aggregates` | un client externe (Claude Desktop, si tu le veux un jour) | 7 outils de totaux, jamais une écriture |

Avec le jeton `aggregates`, une catégorie ou un mois qui compte moins de 3 écritures est fondu
dans « autres » ou masqué : un total ne révèle pas une transaction. Aucun outil ne renvoie
d'IBAN. Aucun outil ne peut appliquer quoi que ce soit : une proposition est une carte, qui ne
s'applique qu'avec ton Face ID. Un jeton crée au plus 60 propositions par heure.

## Ollama ou MLX

Ollama, recommandé : un service macOS qui utilise le GPU, `ollama pull` pour les modèles, et un
appel d'outils fiable. Le brain parle l'API compatible OpenAI, que `mlx_lm.server` expose aussi :
passer à MLX ne change que `llm_url` et `model` dans `deploy/settings.toml` (section `[brain]`).

Modèle par défaut : `qwen3:32b` (environ 20 Go, tient largement dans 64 Go). Plus rapide mais un
peu moins sûr : `qwen3:30b-a3b`. Tout modèle qui gère l'appel d'outils convient.

## Mise en place (une fois)

Depuis le clone du dépôt (`~/personal-hub/personal-hub`), avec l'alias `hubc` de
[mac.md](exploitation/mac.md).

1. **Ollama** : installe l'app (ollama.com) ou `brew install ollama && brew services start
   ollama`, puis :
   ```
   ollama pull qwen3:32b
   curl -s http://localhost:11434/v1/models     # doit lister qwen3:32b
   ```
   Laisse Ollama écouter sur `127.0.0.1` : Docker Desktop (comme OrbStack) fait suivre
   `host.docker.internal` vers le Mac, et rien d'autre sur le réseau ne doit joindre le modèle.
2. **Deux jetons** (affichés une seule fois, chacun avec sa date de fin : 90 jours par défaut,
   `--days` jusqu'à 366) :
   ```
   hubc run --rm --no-deps scheduler hub token create brain-mac -s brain=finance --days 180
   hubc run --rm --no-deps scheduler hub token create claude-aggregates -s aggregates
   ```
   `brain` seul n'ouvre que les agrégats ; `brain=finance` (ou `brain=finance,agenda`) ajoute la
   lecture et les propositions des domaines nommés. Quatorze jours avant la fin, ntfy prévient ;
   `hub token rotate ID` donne un nouveau secret (mêmes portées, l'ancien révoqué) à remettre
   dans `brain.enc.yaml`.
3. **Le fichier de secrets du brain**, chiffré, comme pour les collecteurs :
   ```
   age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/brain.enc.yaml
   ```
   puis colle, et termine par Ctrl-D :
   ```yaml
   brain:
     brain: "hub_…"          # jeton brain-mac
     aggregates: "hub_…"     # jeton claude-aggregates (facultatif)
   ```
   Le chemin est `HUB_BRAIN_SECRETS` dans `deploy/.env`. Pour un autre modèle Ollama déjà
   présent, `HUB_BRAIN_MODEL=<nom affiché par ollama list>` dans le même fichier.
4. **Déployer** : `make deploy TAG=v0.7.0`, puis ajoute `brain` aux profils de `deploy/.env`
   (`COMPOSE_PROFILES=collectors,brain`) et `hubc up -d`.
5. **Contrôle de bout en bout** :
   ```
   hubc exec brain hub-brain check
   ```
   Il vérifie le hub, la présence du modèle, puis pose « Combien ai-je dépensé en restaurants ce
   mois-ci ? » et compare la réponse au chiffre de l'outil. C'est le critère de sortie du lot 7.

## Au quotidien

```
hubc exec brain hub-brain ask "Où en est mon budget alimentation ?"
hubc exec brain hub-brain suggest --dry-run      # voir les suggestions sans créer de carte
hubc exec brain hub-brain suggest                # créer les cartes maintenant
hubc exec brain hub-brain catchup --dry-run      # rattrapage : la règle qu'il proposerait par commerçant
hubc exec brain hub-brain catchup                # jusqu'à 50 règles, à valider ensemble (« À valider »)
hubc exec brain hub-brain direct --dry-run       # achats uniques : la catégorie qu'il choisirait
hubc exec brain hub-brain direct                 # une carte par catégorie, sans règle
```

`catchup` sert à vider une longue file « À classer » : une règle par commerçant (le motif est le
nom du groupe, le sens celui du groupe), qui classe le passé et les imports suivants. Un
commerçant déjà proposé ne revient pas ; relance-le une heure plus tard pour les 50 suivants.
Pour tout rattraper d'un coup, monte `HUB_PROPOSALS_PER_HOUR` dans `deploy/.env` (par exemple
300), relance `hubc up -d`, puis `catchup --limit 300` ; remets 60 ensuite.

`direct` finit la file quand il n'y reste que des achats uniques (un commerçant vu une seule
fois ; `--max-count 2` pour deux) : une règle n'y servirait à rien. Le modèle choisit une
catégorie par commerçant, puis une carte par catégorie réunit les écritures (30 au plus). Dans
« À valider », « Voir les écritures » déplie la carte : décoche celles qui ne vont pas, le reste
se valide du même Face ID. Un commerçant dont le modèle n'est pas sûr reste à classer à la main
et n'est plus redemandé.

Le Mac éteint ou Ollama arrêté, le passage de 8 h 30 échoue sans rien casser ; il reprend le
lendemain.

## Claude Desktop, en agrégats seulement (facultatif)

Si tu veux un jour faire analyser tes chiffres par Claude sans lui montrer une transaction, ajoute
à `~/Library/Application Support/Claude/claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "personal-hub": {
      "command": "/usr/local/bin/docker",
      "args": ["exec", "-i", "hub-brain-1", "hub-brain", "mcp", "--token", "aggregates"]
    }
  }
}
```

Claude ne voit alors que les 7 outils de totaux. Le jeton se révoque à tout moment :
`hubc run --rm --no-deps scheduler hub token revoke <id>` (`hub token list` pour l'id).

## Ce qui n'est pas encore là

- Le résumé hebdomadaire écrit par le modèle : il lui faut un endroit où être lu dans l'app ;
  ntfy ne transporte aucun chiffre.
- La sentinelle « garantie qui expire » arrivera avec le domaine Documents.
