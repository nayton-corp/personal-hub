# Journal des changements

## [Non publié]

## [0.24.0] · 2026-11-14

### Finance

- Logos des actifs : les cryptos ont leur vrai logo en couleur (92 symboles : BTC, ETH, SOL,
  ATOM, EGLD, TAO, RENDER, USDC…), les fonds celui de leur émetteur d'après leur nom (iShares,
  Vanguard, UBS, Xtrackers, Invesco, Fidelity ; ZKB par le pack suisse, `fund_logos`). Un actif
  sans logo garde son symbole ou ses initiales.
- Patrimoine, vue Actifs : le même halo que les comptes, à la couleur de la catégorie.

## [0.23.0] · 2026-11-14

### À la mise à jour

- Rien à faire sur la machine : les logos sont des fichiers de l'app, rien n'est demandé à un
  service tiers à l'affichage.

### Finance

- Vrais logos en couleur des comptes, des connexions et des commerçants : BCF, VIAC, IBKR,
  Binance, Coinbase, Coinbase Wallet, KuCoin, SwissBorg, Ledger, MetaMask, Phantom, Trust Wallet,
  MultiversX ; Migros, Coop, CFF, Swisscom, TWINT dans le journal. Partout où un compte s'affiche
  (Comptes, Patrimoine, filtre par compte, répartition, page d'un actif), dans « Ajouter un
  compte » (le choix de la plateforme) et dans les connexions. Un nom sans logo garde son sigle ou
  ses initiales. Les commerçants et établissements suisses viennent du pack pays
  (`merchant_logos`, `institution_logos`).
- Patrimoine : autour du logo d'un compte, un halo à la teinte de sa catégorie (liquidités,
  actions et fonds, crypto…), fixe quel que soit le réglage de la répartition.

## [0.22.1] · 2026-11-14

### Corrigé

- Budget : un mois d'avant le premier budget s'affichait « Erreur interne » dès qu'une catégorie
  était suivie à l'année : sa cible annuelle, absente ce mois-là, était exigée par la réponse.
  Elle peut maintenant manquer (« Sans cible annuelle »).

## [0.22.0] · 2026-11-14

### À la mise à jour

- Rien à faire sur la machine (migration finance 0030 : une colonne ajoutée, vide). Dès la
  première nuit, le hub peut proposer dans « À valider » les achats réguliers qu'il repère.

### Finance

- Stratégies repérées : chaque nuit, le hub cherche dans le journal des achats réguliers du même
  actif (un DCA) et propose la stratégie dans « À valider », avec ce qu'il a vu (une barre par
  échéance) et les garde-fous remplis. Garde-fous : au moins 4 achats d'affilée (6 chaque
  semaine), rythme régulier, montants à ±15 %, série en cours, aucune vente pendant la série. Une
  carte refusée ne revient pas, sauf si le montant ou le rythme change nettement.
- Un 3a se lit au niveau du compte : le versement régulier, pas chaque fonds. Nouvelle cible
  d'achat régulier `account:<id>` (« Le 25 du mois, je verse 600 CHF sur 3a VIAC »).
- Une stratégie repérée et validée part du premier achat : les échéances passées sont posées
  tenues ou passées d'après le journal, et la liste la marque « Repérée ».
- La phrase d'un achat régulier dit « Le 1er du mois » et « 200 CHF » (au lieu de « Le 1 du
  mois » et « 200.00 CHF »).

### App

- Les pastilles (« Active », « à voir »…) étaient hautes de 40 px partout : une règle des
  boutons de l'assistant (`.pill`) s'appliquait à toute l'app et pouvait faire déborder une
  ligne sur téléphone. Elle ne vaut plus que pour ses boutons.

### Cœur

- Une demande de carte d'un domaine (`proposal.request`) peut porter une `create_key` : une seule
  carte pour cette clé, quel que soit son sort.

## [0.21.3] · 2026-11-14

### Corrigé

- Patrimoine : les onglets Comptes / Actifs se collaient sous la barre du haut à la hauteur
  mesurée au premier rendu ; quand le total apparaît au défilement, la barre grandit et les
  onglets passaient à moitié dessous. Ils suivent maintenant sa hauteur réelle.
- Patrimoine : les onglets Comptes / Actifs étaient un sélecteur dont le fond se confondait avec
  la page (un bouton blanc flottant et un mot gris). Ce sont maintenant des onglets soulignés, sur
  une seule ligne avec « Trier », le nombre d'éléments à côté de l'onglet actif : l'en-tête collé
  passe de 127 à 49 px.
- Patrimoine : tourner le téléphone en paysage ouvre la courbe en plein écran, comme prévu par la
  refonte ; revenu en portrait, elle se referme (sauf si le plein écran avait été ouvert à la main).
- Patrimoine : plus de total dans la barre du haut. Il apparaissait et disparaissait au
  défilement, et la barre changeait de hauteur à chaque fois.
- Patrimoine : la carte Stratégies ouvre son détail dans le même grand panneau que Répartition et
  Rendement, au lieu de se déplier sur la page.
- Panneau Période : il tient sans défiler sur un grand téléphone. Lignes plus serrées, épingles
  sans fond (bleues quand la période est dans la barre), et le bouton « Afficher cette plage » sous
  les dates au lieu d'être collé en bas du panneau.

## [0.21.2] · 2026-11-13

### Tests

- Tests d'écran : ils attendaient l'orbe (fixe dans la page) au lieu des onglets dessinés par
  l'app, et partaient trop tôt après un rechargement. La CI de main échouait là, et ni la 0.21.0
  ni la 0.21.1 n'ont été publiées : cette version les reprend.

## [0.21.1] · 2026-11-13

### Sécurité

- opentelemetry-api 1.45.1 → 1.45.2 (CVE-2026-126360, signalée par l'audit des dépendances) :
  la CI de la 0.21.0 échouait sur ce seul point, et la version n'était donc pas publiée.

## [0.21.0] · 2026-11-13

### À la mise à jour

- Rien à faire sur la machine (migrations finance 0028 et 0029, tables nouvelles et vides). Les
  chiffres ne bougent pas tant qu'aucun bien n'est saisi. L'icône de l'écran d'accueil change :
  sur iPhone, retirer puis rajouter l'app à l'écran d'accueil pour la voir.

### Finance

- Refonte de l'affichage, d'après le prototype validé. Finance a sa barre du bas (Aperçu,
  Patrimoine, Budget, Journal) et ses réglages, ouverts par la roue : Ajouter un compte, Comptes
  et biens, Dettes, État des sources, Budget, Impôts et 3a, Exporter. Les réglages du hub
  (profil, affichage, sécurité, état, espaces) restent sur l'accueil.
- Patrimoine : une seule pilule de filtre ; toucher un compte filtre l'écran. Les périodes sont
  au-dessus de la courbe ; le bouton Affichage, à droite du total, range la vue, la légende, la
  règle et le plein écran. Répartition et Rendement (Risque en vue Rendement) sont des cartes qui
  ouvrent leur détail dans un grand panneau ; Stratégies se déplie sur place. Un cadre seulement
  autour de ce qui se touche : la courbe et les listes sont à plat.
- Budget : chaque barre est la part du budget de sa catégorie, en pourcentage, avec le trait du
  rythme attendu à ce jour ; rouge quand le budget est dépassé.
- Journal : un appui long sur une écriture ouvre la sélection ; plusieurs écritures se classent
  d'un coup, sous une seule validation.
- Biens hors comptes : logement, véhicule, objet de valeur, prêt accordé. Une valeur datée, une
  variation par an facultative (−15 % proposé pour un véhicule). Un bien compte dans le
  patrimoine et la répartition (« Biens »), jamais dans le rendement. Proposition `save_good`,
  route `/api/finance/goods` (migration finance 0028).
- Frais des fonds : la carte chiffre ce que coûtent les frais courants (TER) par an, et l'écart
  sur 30 ans à 5 % par an avant frais. Le TER se saisit par fonds ; sans lui le fonds est noté
  « frais inconnus », rien n'est deviné. Proposition `set_fund_fee`, route `/api/finance/fees`
  (migration finance 0029). Carte Revenus : dividendes et intérêts reçus sur 12 mois.
- Première visite : sans compte, l'Aperçu propose six étapes (premier compte, autres comptes,
  biens et dettes, classement, budget, passkey de secours) ; ensuite une carte « Mise en route »
  suit l'avancement, et se retire d'un geste.

### Hub

- Nouvelle icône (trait qui monte vers un point bleu, sur fond nuit), en SVG pour l'onglet du
  navigateur et en PNG pour l'écran d'accueil.
- Aucun écran ne dépasse en largeur à 320, 375 et 390 px : vérifié par les tests d'écran.

## [0.20.0] · 2026-11-12

### À la mise à jour

- Rien à faire sur la machine. Les sections du patrimoine (Répartition, Performance,
  Stratégies) sont repliées à chaque ouverture de l'app.

### Finance

- Stratégies : une décision écrite une fois, en une phrase, que le hub aide à tenir. Trois
  genres : vendre par paliers (crypto, par rapport au prix d'achat : une pièce, les altcoins ou
  toute la crypto), achat régulier (chaque mois ou chaque semaine), acheter une grosse baisse
  (15 % au moins sous le plus haut des 3 ou 12 derniers mois). Le hub ne passe jamais d'ordre :
  chaque nuit il regarde si une étape est atteinte, prévient une fois (notification sans actif
  ni montant), puis coche l'étape quand l'opération apparaît au journal, ou prend la réponse
  « C'est fait », « Plus tard », « Je passe ». Une étape à la fois, des seuils larges, un seul
  rappel pour un achat régulier. Section « Stratégies » du patrimoine, ligne « À faire » sur
  l'accueil, propositions `save_strategy` et `answer_strategy_step`, route
  `/api/finance/strategies`, outil `finance_strategies` (migration finance 0027).
- Patrimoine : Répartition, Performance et Stratégies se replient, et sont repliées par défaut ;
  repliée, chacune tient en une ligne. La liste des comptes est à portée de pouce.

## [0.19.1] · 2026-11-12

### Finance

- Compositions des fonds : le collecteur lit aussi le site suisse d'iShares, pour les ETF
  domiciliés en Suisse (iShares SMI, SMIM, Core SPI…). Un fonds qui suit le SMI peut ainsi lire
  la composition de l'iShares SMI ETF (CH) via « Fonds répliqués ».

## [0.19.0] · 2026-11-12

### À la mise à jour

- Rien à faire sur la machine. Au premier passage du collecteur « Cours et cryptos », le hub
  reçoit la composition des fonds iShares détenus. Pour un fonds sans fichier lisible, règle
  « Fonds répliqués » dans « Cours et cryptos » : l'ISIN du fonds, puis celui d'un ETF iShares
  qui suit le même indice.

### Finance

- Compositions des fonds mises à jour seules : une fois par jour au plus, le collecteur
  « market » demande au hub ses fonds détenus (un ETF rangé parmi les actions compris) et
  dépose, pour chacun dont la composition a au moins 7 jours, la liste des lignes publiée par
  iShares. Un fonds d'un autre émetteur lit l'ETF du même indice (réglage `funds`). Un fonds dans
  une seule case (or, immobilier suisse) n'est plus cherché. Seuls des ISIN quittent la machine.
- Une liste de lignes iShares lit sa date (« 10/Nov/2026 ») ; ses liquidités et dérivés sans
  pays vont dans « Non réparti » plutôt que dans « Autres ».

### Cœur

- `GET /collectors/<connexion>/needs` : un domaine peut dire à un collecteur ce qu'il doit
  chercher à son passage (`CollectorNeeds`, facultatif). Réservé au service collecteur.

## [0.18.3] · 2026-11-10

À côté d'un gain en francs, le rendement de ton argent.

### À la mise à jour

- Le pourcentage sous le grand chiffre du Patrimoine change de définition : c'était le rendement
  pondéré dans le temps, qui ignore les montants (+16 % affichés pour 1 214 francs gagnés) ;
  c'est maintenant le rendement de l'argent engagé, qui va avec les francs. Le rendement pondéré
  reste dans la section Performance, où il sert à se comparer à un indice.
- Rien à faire sur la machine. L'étalon (`golden check`) ne bouge pas : un chiffre apparu depuis
  la photo n'est pas un écart, à toute profondeur.

### Finance

- Patrimoine : sous le grand chiffre (tout le patrimoine, un compte, un actif), le gain en
  francs est suivi du rendement de l'argent engagé. Jusqu'à un an, celui de la période : le
  gain rapporté au capital moyen, chaque apport compté depuis son jour. Au-delà, le taux annuel
  exact, « par an ». Dans la liste des comptes et des actifs, et le doigt sur la courbe, le
  pourcentage suit la même règle jusqu'à un an ; au-delà, les francs seuls plutôt qu'un taux
  approché.
- La section Performance et la bande d'un compte nomment leur chiffre : « pondéré dans le
  temps », « Rendement pondéré ».
- Accueil : le pourcentage sur 30 jours de la tuile Patrimoine est celui des seuls avoirs. Un
  crédit dans le total réduisait sa base et grossissait le chiffre.
- `/finance/performance` : `personal` dans chaque point et chaque résumé, et `owned`, le résumé
  des seuls avoirs quand la sélection contient un crédit.

## [0.18.2] · 2026-11-10

Le gain et le rendement n'oublient plus les positions vendues.

### À la mise à jour

- Le gain et le pourcentage changent dans les vues qui nomment leurs lignes : un patrimoine
  avec un crédit, la vue Brut, une vue filtrée, la page d'un compte. Ils comptent maintenant
  les positions vendues pendant la période, comme la vue de tout le patrimoine le faisait déjà.
- Rien à faire sur la machine. L'étalon (`golden check`) ne bouge pas.

### Finance

- Performance : dès qu'un crédit était dans le total, en vue Brut ou avec un filtre, l'app
  demandait au serveur les seules lignes qu'elle connaît, celles d'aujourd'hui. Une position
  vendue ou vidée depuis sortait du calcul avec son passé : le gain et le rendement de la
  période étaient ceux des seules positions encore détenues. `/finance/performance` prend
  `account=` (un compte entier, lignes passées comprises) et l'app demande ainsi tout compte
  dont elle choisit toutes les lignes. Un actif choisi (page ou filtre « Actif ») reste demandé
  ligne par ligne.

## [0.18.1] · 2026-11-10

L'hygiène du second audit (10 novembre, lot E). Aucun chiffre ne change.

### À la mise à jour

- Une hausse d'abonnement déjà signalée peut l'être une dernière fois : la clé de l'alerte
  change (l'abonnement et son nouveau prix, plus la date du paiement).
- Une migration du cœur (`0010_event_retries`) : la file de renvoi des alertes.
- Rien à faire sur la machine.

### Cœur

- Alertes (audit N1, N3) : une notification que ntfy n'a pas prise est renvoyée aux passages
  suivants, pendant un jour, au lieu d'être perdue ; un événement dont le traitement échoue
  n'arrête plus les cartes et les alertes de son domaine : il attend dans `event_retries`, et
  après cinq essais il est mis de côté avec une alerte.
- Paliers (audit A2, [D-028](docs/decisions.md)) : la déclaration `external_text = false` d'un
  programme ne suffit plus pour éviter la carte. Il faut la portée `core:auto`, donnée par la
  personne, et jamais à un jeton qui lit des textes. Aucun jeton en service ne l'a.
- Le résumé du jour découpe la journée à l'heure de l'instance, plus en UTC.
- Limite connue du jeton d'agrégats (audit X3) écrite dans [docs/securite.md](docs/securite.md).

### Finance

- Une hausse d'abonnement prévient une fois, pas à chaque paiement (audit N2).
- La pastille « à classer » du Journal lit une route légère (`/finance/todo`) au lieu de
  recalculer les chiffres clés (audit P1).
- Le prix de revient des positions se lit en une fois, plus une requête par position (audit Q4).
- Le seuil sous lequel un jour n'a pas de rendement est une unité de la devise de base, plus
  100 centimes fixes (audit Q6). Le montant visé d'un compte suit la devise du compte.
- Une archive zip sans relevé est refusée avec une trace, au lieu d'être avalée.

### Qualité et chaîne de publication

- Les actions GitHub et l'image gitleaks sont épinglées par empreinte (audit S3) ; Dependabot
  les suit.
- Deux plafonds qui ne peuvent que baisser (audit Q1, Q2) : les `Any` de `hub/` et les lignes
  de plus de 200 caractères de l'app (`tests/test_code_ceilings.py`).

## [0.18.0] · 2026-11-10

La courbe, la répartition et le budget du second audit (10 novembre), tels que validés sur la page
« avant / après ». Aucun chiffre du patrimoine ne change.

### À la mise à jour

- Courbe : au-delà de six mois, un point par dimanche (par fin de mois sur les très longues
  périodes) au lieu d'un jour sur N. Le plus haut et le plus bas affichés sont ceux de tous les
  jours, à leur vraie date : ils peuvent différer de ceux d'avant.
- « Apports nets » partout, y compris sur le patrimoine total (plus de « Versé » ni d'« Épargne »
  selon l'écran). La ligne reste à activer.
- Répartition : par secteur, par région et par devise portent sur tout le patrimoine affiché. Les
  liquidités ont leur case, « Non réparti » est la part qu'un fonds ne détaille pas, « Secteur
  inconnu » un actif sans fiche. La ligne sous les blocs dit la part sûre et la part estimée.
- Budget : les barres sont à la même échelle d'une catégorie à l'autre (longueur = montant), une
  seule couleur, rouge seulement au-delà de la cible. Les charges fixes n'ont plus de barre :
  « Payé le 1 nov. » ou « Attendu vers le 15 nov. ». La tendance montre le budget de chaque mois
  (trait pointillé) et ce qui le dépasse.
- `hub finance golden check` : le plus haut et le plus bas de la courbe, apparus avec cette
  version, ne comptent pas comme un écart face à une photo prise avant.

### Finance

- Courbe (audit, lot C) : l'échantillonnage est calé sur le calendrier (`returns._sample` :
  jour, dimanche, fin de mois, le pas s'élargit au-delà de 400 points), la courbe d'une période ne
  change plus de forme selon le jour où on la regarde. `/performance` donne `extremes` (plus haut
  et plus bas sur tous les jours). Le pas demandé par l'app et le mot affiché (« par semaine »)
  viennent de `wcurve.js`. La zone entre la valeur et les apports a sa légende (Gain, Perte).
- Répartition (audit, lot B) : un seul calcul, côté serveur, sur les lignes de la courbe
  (`patrimoine/app/allocation.py`) : la somme des cases, dettes à part, est le patrimoine affiché.
  Chaque case dit sa nature (`kind` : nommée, liquidités, non détaillée, inconnue), si elle est
  estimée et les actifs qui la remplissent ; les positions sans cours sont nommées (`unpriced`).
  `/lookthrough` accepte `line` (la sélection de l'écran). Le navigateur n'ajoute plus rien.
- Budget (audit, lot D) : `/budget` donne `paid_on` et `expected_on` aux charges fixes
  (`classement/app/due.py`), `/budget/months` donne `budget`, `budgeted_expenses` et `over` par
  mois, dans le périmètre du reste à vivre. « Hors cible » se déplie. L'écran est découpé
  (`bviews.js`, `bflow.js`), `budget.js` repasse sous 400 lignes.

## [0.17.0] · 2026-11-10

Les urgences du second audit (10 novembre). Aucun chiffre du patrimoine ne change.

### À la mise à jour

- Budget : une charge fixe payée à la tolérance près (une unité, ou 1 % de la cible) passe de
  « Dépassé de 0 » à « Payé ». Une cible à zéro disparaît de l'écran (« hors budget »).
- `hub ops health` tourne chaque heure. Tant qu'aucun dépôt restic hors de la machine n'est
  déclaré, il le rappelle une fois par semaine (« Pas de sauvegarde hors de la machine ») : voir
  [docs/exploitation/pi.md](docs/exploitation/pi.md#une-copie-hors-du-pi).
- À faire une fois sur la machine : `hub backup --restic` puis `hub backup-check`, pour voir
  l'essai de restauration passer avec le vrai restic (les tests le remplacent par un faux).
- « À valider » : une carte proposée par un assistant n'est plus cochée d'avance.

### Exploitation

- Être prévenu (audit O1, D1) : un job de la crontab qui échoue donne une alerte ntfy ; le
  contrôle de nuit nomme ce qui a échoué (`hub verify --notify`). `hub ops health`, chaque heure,
  regarde les disques (85 %), le retard de la réplique Litestream, l'âge de la copie de nuit, du
  passage restic et du contrôle de nuit, les imports restés en plan et les échéances déclarées
  (`HUB_EXPIRIES`, par exemple le jeton GHCR du Pi) : une alerte à l'apparition, un rappel par
  jour, un mot quand c'est réglé. Quand tout va bien, un signal de vie part vers
  `monitoring.heartbeat_url` des secrets : son absence dit que la machine est éteinte.
- Sauvegardes (audit E1, K1) : restic sauvegarde aussi la configuration (secrets chiffrés,
  secrets des collecteurs, `deploy/.env`) et la réplique, vers le dépôt local puis vers un dépôt
  hors de la machine s'il est déclaré (`repository_offsite`, `env` dans la section `restic` des
  secrets). Chaque dimanche, `hub backup-check` contrôle chaque dépôt, en ressort les dernières
  copies des bases, les compare aux originaux et leur passe `integrity_check`. Les copies
  d'avant migration ne s'accumulent plus (trois gardées). Kit de secours réécrit.
- `hub verify` à deux niveaux (audit V1, [D-027](docs/decisions.md)) : l'intégrité bloque une
  mise à jour ; un écart entre deux calculs (`figures.crypto_gap`) sort en `warnings`, alerte par
  ntfy et ne bloque plus rien. La 0.16.7 avait été refusée pour un écart de ce genre.
- Journaux des conteneurs bornés (10 Mo, trois fichiers).

### Finance

- Import (audit I1) : un import interrompu (redémarrage, base occupée) est repris depuis
  l'archive chiffrée au passage suivant, au lieu de rester « en attente » pour toujours ; au-delà
  d'une heure, il est signalé. La boucle de la boîte d'entrée survit à un échec et alerte au
  troisième de suite.
- Budget (audit B1, B3) : une charge fixe se juge à la tolérance près (une unité de la devise
  ou 1 % de la cible) : 1'336.05 payés pour une cible de 1'336 sont « Payé », plus « Dépassé de
  0 ». Un écart sous l'unité s'affiche avec ses décimales. Une cible se retire (« Retirer la
  cible ») : la catégorie redevient « hors budget ».

### Collecteurs

- Base (audit X1) : l'explorateur public répond 403 ; le manque disait « réponse illisible,
  nouvel essai au prochain passage » à chaque heure. Le réseau passe en « solde seul » : solde lu
  chaque jour, historique redemandé une fois par semaine (`blocked`), dit sur la connexion et
  plus dans « À faire ». Un mouvement non expliqué sort au rapprochement. Un 403 avec une clé
  Etherscan se dit « clé refusée ».

### App

- « À valider » (audit W1) : le Face ID de l'accueil ne signe que les trois cartes qu'il montre
  et le dit ; « Tout voir » porte les autres. Une carte proposée par un assistant, ou qui a
  changé depuis sa lecture, n'est jamais cochée d'avance.

## [0.16.9] · 2026-11-10

### Exploitation

- Mise à jour : quand le `verify` d'avant migration échoue avec l'image en place, la nouvelle
  image le refait sur les mêmes bases et la mise à jour continue si elle le passe. Sans cela,
  une version qui corrige un contrôle des chiffres (0.16.8) ne pouvait jamais s'installer : le
  Pi restait en 0.16.6, dont le calcul faisait échouer son propre contrôle.

## [0.16.8] · 2026-11-10

### Finance

- Cryptos, résultat depuis l'achat : il s'accorde de nouveau avec la courbe « Max ». Le prix
  de revient se trompait dans trois cas : des parts en route entre deux de mes comptes (l'arrivée
  lue après une vente faite avec, fréquent sur USDC SwissBorg → Binance) sortaient du compte
  global, la vente passait « sans historique » et l'arrivée gardait le coût ; une vente lue avant
  l'achat du même jour qui la couvre ; des frais payés en crypto qui emportaient leur part du coût
  sans la compter en perte. Le contrôle de `hub verify` qui compare les deux chiffres a refusé
  d'installer la 0.16.7 dès que les ruptures sont tombées à zéro.
- `hub verify` : l'écart permis entre les deux chiffres compte aussi ce que le résultat montre à
  part (parts sans prix de revient, sorties que l'historique ne montre pas), que la courbe compte
  au cours du jour.

## [0.16.7] · 2026-11-10

### Finance

- Patrimoine : avant le premier cours d'un actif, la courbe prend d'autres prix réels au lieu de
  se dire « estimée » : un stablecoin vaut un dollar, le premier cours vaut pour la semaine qui
  le précède (le jour de la fusion d'un fonds VIAC), sinon le prix de la dernière opération sur
  l'actif (montant ÷ parts). Les longues plages hachurées (CFG chez KuCoin, anciennes cryptos
  Binance et Coinbase) disparaissent.

## [0.16.6] · 2026-11-10

### Finance

- Binance : la distribution « Token Swap » qui remplace un jeton renommé (RNDR → RENDER,
  MATIC → POL) est un échange : l'ancien jeton sort, le nouveau entre, sans revenu. Avant, seul
  le nouveau entrait et le rapprochement comptait les parts deux fois. Les distributions déjà
  lues sont relues une fois au prochain passage pour ajouter la sortie de l'ancien jeton.
- Coinbase : les cryptos reçues de Coinbase Earn sont des récompenses, plus des dépôts venus
  d'un portefeuille non suivi.
- Portefeuille MultiversX (EGLD, adresse `erd1…`) : solde (délégations et récompenses comprises)
  et historique par l'API publique, sans clé. Un envoi d'EGLD d'une plateforme vers ce
  portefeuille devient un virement entre mes comptes.

## [0.16.5] · 2026-11-09

### Exploitation

- Publication : nouveau cache de construction des images. La 0.16.4 n'a pas pu publier l'image du
  collecteur (ghcr refusait une couche venue de l'ancien cache) ; la 0.16.5 la contient.

## [0.16.4] · 2026-11-09

### Finance

- VIAC : l'avis « Transaction de fonds » (fusion d'un fonds dans un autre à valeur égale, comme
  les fonds CS repris par UBS fin octobre 2026) est lu : les parts de l'ancien ISIN sortent et
  celles du nouveau entrent, au coût moyen de l'ancien, sans écriture de liquidités ni de titres.
  Il était refusé, et les rapports suivants montraient des parts sorties de nulle part.
- Import : un PDF VIAC refusé puis déposé à nouveau est relu (au lieu d'être écarté comme
  doublon) ; s'il se lit désormais, il reprend son import refusé.

## [0.16.3] · 2026-11-09

### Finance

- Binance : l'export « Historique des trades Spot » du site en français (`N° de commande,Durée,
  Paire,Côté,…`) est lu ; les exécutions d'un même ordre font une opération. Un ordre déjà au
  registre (lu par l'API : même actif, même quantité, à un jour près) est sauté : l'export
  entier se dépose sans doublon. L'API ne rend plus les échanges anciens (2021-2022), même sur
  des paires encore cotées : c'est par ce fichier qu'ils entrent.

## [0.16.2] · 2026-11-09

### Collecteurs

- VIAC : les documents « Transaction de titres » sont récupérés. VIAC s'en sert pour la sortie
  d'un fonds quand il le fusionne dans un autre (fonds CS repris par UBS fin octobre) ; le bot les
  ignorait, et l'entrée dans le nouveau fonds, lue comme un achat, laissait un écart.
- VIAC : un document d'un type inconnu est noté une fois au journal (`viac.document_ignored`, date
  et titre) et dans la mémoire du collecteur (`ignored`), au lieu de disparaître sans trace.

## [0.16.1] · 2026-11-09

### Collecteurs

- KuCoin : les ordres du marché spot (type « Spot » au grand livre) deviennent des échanges, les
  deux côtés de l'ordre regroupés ; ils étaient comptés comme type inconnu et laissés de côté.
  L'historique déjà lu est relu une fois de lui-même (version d'historique 3).

### Exploitation

- pi.md : `HUB_SKIP_TRIAL=1` sur le Pi (l'essai est déjà fait par la CI) ; une mise à jour prend 1 à 2 min.
- `mac-preflight.sh` lit les droits de la clé age avec le `stat` de Linux sur le Pi : il y affichait
  « clé age en File: … » et refusait de déployer (donc aussi la mise à jour automatique).

## [0.16.0] · 2026-11-09

### Exploitation

- `deploy/pi-ssd-setup.sh` déplace aussi `/var/lib/containerd` sur le SSD : Docker 29 y range ses
  images (17 Go sur le Pi), qui restaient sur la carte SD.

### Exploitation

- Le hub passe sur le Pi ([pi.md](docs/exploitation/pi.md), D-026). La fusion de la PR de
  version publie : `release.yml` pose lui-même le tag quand la version de `pyproject.toml` n'en
  a pas, puis publie les images et la release. Sur le Pi, le minuteur `hub-autoupdate`
  (`make autoupdate-install`) installe chaque nouvelle release avec `deploy/deploy.sh`, fige et
  recompte les chiffres (`golden save` / `golden check`) et prévient par ntfy (`hub ops
  notify`).
- `deploy.sh` met `HUB_TAG` de `deploy/.env` à la version déployée.
- L'adresse de l'assistant et du pont Rappels/Calendrier se règle dans `deploy/.env`
  (`HUB_ASSISTANT_URL`, `HUB_AGENDA_BRIDGE_URL`) ; une variable `HUB_<DOMAINE>__<CLÉ>`
  l'emporte sur la section du domaine dans `settings.toml`.

## [0.15.1] · 2026-11-09

### Collecteurs

- KuCoin : un appel refusé pour son horodatage (HTTP 400, `400002`, un appel arrivé trop tard) est
  relancé deux fois avec un horodatage neuf. Un seul refus sur les centaines d'appels du grand
  livre faisait écarter tout l'historique du premier passage.

### App

- « Ajouter un compte » passe dans la rubrique Comptes, en tête, et s'ouvre sur sa propre page :
  chaque étape remplace la précédente, la fin (ou « Annuler ») ramène à Comptes, et la page
  repart de l'étape 1 à chaque ouverture. Les comptes en attente suivent dans Comptes ; la
  rubrique Connexions ne garde que les connexions. Une rubrique de domaine peut être une page
  hors de la liste (`SettingsSection.listed=False`).

## [0.15.0] · 2026-11-04

### App

- « Ajouter un compte » en trois étapes : le type (banque, titres, prévoyance, plateforme
  crypto, portefeuille, autre), la plateforme, puis ce qu'elle demande (identifiants, banque
  Enable Banking, adresses publiques, ou rien pour un compte tenu à la main). La connexion se
  crée en passant et sert les comptes suivants de la même plateforme ; une plateforme crypto
  ou un portefeuille a son compte tout de suite, avec Face ID. Le bouton « Ajouter » de la
  carte Connexions disparaît : ses réglages restent sous « Régler ».
- La fiche d'un compte dit ce qui l'alimente (« Alimenté par KuCoin · dernier relevé il y a
  2 h ») et l'actualise d'un toucher.

### Collecteurs

- KuCoin : le premier passage lit le grand livre depuis le plus ancien dépôt ou retrait, et non
  plus sur un an seulement. Un compte resté sans mouvement depuis plus d'un an retrouve ses
  dépôts et retraits anciens. Les comptes déjà lus sont relus une fois d'eux-mêmes (version
  d'historique 2), sans réglage à toucher.

## [0.14.0] · 2026-11-04

### Assistant et sécurité

- L'assistant de la maison reconnaît ses appelants à leur jeton (`listen.callers`,
  `ASSISTANT_CALLER_<NOM>` dans son `.env`) et en déduit pour qui chacun parle : le hub parle
  toujours pour son propriétaire, Domia nomme la personne de l'appareil parmi celles permises.
  Sans jeton connu, `401` ; l'adresse (`allow_from`) n'est plus qu'une seconde barrière. Le hub
  présente `assistant.token` de `secrets.enc.yaml` (créé par `hub init`) et ne passe plus de
  personne ; `HUB_ASSISTANT__PERSON` disparaît.
- Passkeys (audit M16) : en ajouter une demande le Face ID d'une passkey en place
  (`POST /auth/passkey/confirm/begin`, puis `confirm` dans `register/begin`), jamais la session
  seule ; `DELETE /auth/passkeys/{id}` en retire une (jamais la dernière) et ferme ses sessions.
  Migration core 0009 (`passkeys.revoked_at`).
- L'API ne gèle plus pendant un import ou une phrase dite à l'orbe (audit M13) : le corps se
  lit en flux, borné, et le travail part dans le threadpool ; un test d'architecture interdit
  à une route `async` d'appeler un port en direct. `server.forwarded_allow_ips` (Caddy) remplace
  « * » ; une seule lecture d'évènements à la fois ; le texte d'une exception passe aussi par le
  filtre des journaux.

### Finance

- Un seul moteur de valorisation (audit C2, M1, m4) : la série du patrimoine
  (`patrimoine/model/engine.py`, pure, gelée une fois construite) donne la valeur et le flux de
  chaque ligne et les versements cumulés, jour par jour ; `networth`, `kpis`, les instantanés,
  la performance, le résultat des cryptos et le rapprochement la lisent, ou lisent les mêmes parts
  et cours (`model/positions.py`). Les versements en devise sont convertis au change de leur
  jour, plus de celui de la valorisation : sur un compte en devise, l'effet marché comprend le
  change (les versements cumulés d'un tel compte changent ; le patrimoine, non). Une rupture
  « sans historique » gardée telle quelle sans cours ce jour-là demande un coût au lieu d'en
  poser un à 0. La série est gardée en mémoire par base, tant que rien n'a changé.
- Les mouvements crypto ont leur table (audit C1, M2) : `crypto_moves` (rôle, crypto, parts,
  txid) et `crypto_links` (l'autre côté d'un mouvement : virement entre mes comptes, mise ou
  sortie de staking), écrits une fois par la source ou par une carte validée, retirés par une
  ligne de retrait ; `fx_json` ne garde que le change. Plus rien n'est deviné à la lecture : un
  envoi et une arrivée à quelques jours et frais près, ou une sortie de staking suivie de son
  claim, deviennent des cartes `link_crypto_moves` (inverse `unlink_crypto_moves`), que le hub
  redemande après chaque import et chaque nuit ; en attente, le mouvement reste « hors de mes
  comptes » avec sa rupture. La migration finance 0022 reprend les jambes et applique les
  anciennes règles une dernière fois (liens `legacy|…`, acteur `migration:0022`). Les deux
  côtés d'un virement apparié entre mes comptes ne comptent plus comme versements, quelle que
  soit leur catégorie.
- Aucun zéro silencieux (audit M6, M7, M8, m6) : un montant sans change marque la série
  partielle au lieu de valoir 0 ; un change de plus de 7 jours ouvre une rupture « change
  ancien » (`stale_fx`, décision « garder tel quel ») ; une décision « sans cours » ou « cours
  ancien » couvre les parts qu'elle a vues et se rouvre si elles changent ; un collecteur dont
  une adresse dépasse les pages lues le dit (`partial history.<portefeuille>:truncated`) et
  relit tout au passage suivant ; une santé « error » et des réglages de mois absents sont
  journalisés et montrés.
- Tout passe par le Double Sas (audit C5, M9, m1, m5) : une décision de rapprochement est la
  proposition `decide_break` (annulable par `withdraw_break_decision`), le jour de début du
  mois budgétaire est la proposition `set_month_start`, datée (règles `budget_period_rules` :
  les mois d'avant gardent leur découpage), les soldes constatés des dettes sont en ajout seul
  (`debt_balance_records`, le dernier relevé d'un jour fait foi). `POST /finance/breaks/decide`
  et `POST /finance/settings` disparaissent ; `GET /finance/settings` rend les règles. Une
  lecture n'écrit plus : `transfers`, `networth/history` et `/proposals` rafraîchissent après
  la réponse. Migration 0021, additive.
- Budget (audit C3, M3, M4, M5, m9) : une dépense en devise compte au change de son jour, et
  sans change elle est signalée (`missing_fx`) au lieu de valoir 0 ; une cible est gardée telle
  que saisie avec sa cadence (`set_budget` prend `amount_minor` et `cadence`, migration 0023,
  les anciennes lignes mensuelles restent lisibles) ; le rythme, l'état et la projection d'une
  période viennent du serveur (`classement/model/pace.py`), la même règle pour l'app et les
  sentinelles, et le front ne divise plus par 100 : l'exposant de la devise vient du profil
  (`currency_exponent`). La table des changes est lue par le registre (`registre/app/fx.py`).
- Corriger une écriture (audit M14) : la proposition `correct_entry` (montant, date ou compte,
  avec un motif) écrit une annulation puis une remplaçante (`kind` `correction`,
  `corrects_seq`), la catégorie suit, l'original reste et montre ses corrections dans le
  Journal, qui propose le geste ; inverse : corriger la remplaçante avec les valeurs d'origine.
  Les corrections comptent dans les soldes vérifiés contre les relevés (BCF, IBKR, VIAC) ; les
  instantanés se recalculent après une correction.
- Historique Binance jamais tenu pour lu (audit M15) : chaque flux garde son curseur
  (`stream_since`) ; une fenêtre refusée reste à relire, est déposée dans le fichier (`gaps`,
  format `hub.market.v1`) et devient une rupture « historique non lu » (`source_gap`, avec
  `until`, décision « garder tel quel » couvrant la fenêtre vue) ; une paire que l'API ne liste
  plus se déclare dans `pairs` des secrets, et l'export CSV « Trade History » de Binance se
  dépose comme un relevé (`binance_csv`). Migration 0024 (`source_gaps`, décisions acceptant
  cette rupture).
- Contrats d'API (audit M10, m9) : les trente routes Finance déclarent leur modèle de sortie
  (`response_model`, un module `schemas.py` par sous-contexte ; `search` rend `EntrySearchOut`)
  et un test vérifie, sur un jeu de données complet, qu'aucune réponse ne porte un champ hors
  modèle. `make openapi` génère aussi `hub/web/api.d.ts` depuis l'OpenAPI, et `make web` passe
  `tsc` sur les modules marqués `// @ts-check` (`format.js`, `bmodel.js` pour commencer).
- L'assistant à parité avec l'app (audit M11, M12) : 47 outils Finance au lieu de 16. Chaque
  route de lecture a son outil (écritures, une écriture, ordres, réglages, flux, budget mois
  par mois, historique du patrimoine, positions, performance, transparence, cours, ruptures,
  dettes, virements, packs de règles, comptes à ouvrir), et chaque type de proposition ouvert à
  l'assistant (tous sauf `apply_import`) a le sien, engendré de son modèle de paramètres quand
  aucun outil écrit à la main ne le couvre (`finance_propose_<type>`). Les montants restent du
  texte, jamais d'IBAN ; le jeton des agrégats voit 20 outils de totaux. Un test tient la
  parité routes ↔ outils ↔ types. Une seule boucle d'agent, celle de l'assistant :
  `hub.brain.agent` et `hub-brain ask` disparaissent (leurs tests avec eux ; ceux de
  l'assistant couvrent la boucle), `hub-brain check` fait un tour de conversation et vérifie
  que le modèle demande `finance_month_summary` ; `brain.max_steps` n'a plus d'effet.
- L'assistant sous les mêmes barrières que le hub (audit M12) : `mypy --strict` sur
  `assistant/` (tout `dict` et `list` paramétré, chaque fonction annotée) et la règle des 400
  lignes, tenue par le test du hub : `tools.py` devient la boîte à outils seule, ses familles
  d'outils vont dans `tools_base`, `tools_house`, `tools_knowledge`, `tools_agenda` ;
  `grammar.py` garde l'enchaînement, le lexique dans `grammar_lexicon`, les actes dans
  `grammar_acts` ; `assistant.py` laisse ce qu'il dit à `phrasing`. Rien ne change pour qui
  importe `domia_assistant.tools`, `.grammar` ou `.assistant`.
- `hub finance golden save | check` : l'étalon des agrégats (patrimoine, positions,
  performance, ruptures, budget, dettes) se fige avant une mise à jour et se vérifie après, au
  centime ; le fichier ne contient que des chiffres et des identifiants.

### Pack pays

- Tout ce qu'une instance sait de son pays tient dans un pack (audit M17, m13),
  `hub/domains/finance/packs/<pays>` (`ch` : la Suisse) : devise, fuseau et locale proposés à
  l'installation, modules du pays (pilier 3a) et plafonds de l'épargne-retraite, formats des
  libellés de carte et localités de la banque, consignes de l'IA pour le classement (contexte,
  contenu des catégories, règle du paiement mobile), régions domestique et Europe de la
  transparence des fonds, commerçants, établissements et catégories du pays pour les
  pictogrammes de l'app. Le code générique du hub, de la finance, du brain et du front ne nomme
  plus la Suisse, la BCF ni TWINT ; `tests/test_core_is_generic.py` le vérifie sur le cœur,
  les modules génériques de la finance et le front (commentaires et docstrings exclus).
- Le cœur reçoit les packs par le point d'entrée `hub.country_packs` (qui remplace
  `hub.country_modules`) : `/profile` publie `locale` et `packs` (domaine → ce que son pack
  publie, lu par le brain pour ses consignes) ; le catalogue des connecteurs publie
  `refresh_hint` (ce que demande une actualisation, la validation sur le téléphone pour la
  BCF). Sans `HUB_COUNTRY`, le pays d'une instance sans profil est le premier qu'un domaine
  connaît.
- `hub init` : `--country`, `--tz`, `--currency` et `--locale` n'ont plus de défaut suisse ; le
  pays propose les trois autres, un pays sans pack les demande. `HUB_LOCALE` (compose,
  `fr-CH` par défaut) règle la mise en forme des nombres et des dates dans l'app et le
  navigateur des collecteurs ; l'image n'a plus de fuseau à elle (`TZ=UTC`, compose le pose).
  Le franc suivi dans une autre base est un réglage (`market.currencies`), plus une exception du
  collecteur. `hub finance accounts add` demande `--institution`.
- `/finance/lookthrough` donne à chaque région son code (`home`, `europe`, `north_america`…) ;
  l'app choisit l'icône par le code, les étiquettes gardées en base ne changent pas (« Suisse »,
  « Europe (hors Suisse) »). L'unité « Performance en devise de base » du patrimoine s'enregistre
  sous `money` (l'ancien `chf` est relu). Le nom du module `pillar3a` et les défauts du noyau
  (`DEFAULT_TZ`, `DEFAULT_BASE`, quand compose ne pose rien) restent.

### Mineurs de l'audit

- Seuils en réglages (m2, m16) : la section `[finance]` règle la tolérance du rapprochement,
  les délais d'un compte, d'un cours et d'un change anciens, l'epsilon des quantités et les
  seuils des événements de la courbe de performance (`event_floor_minor`, `event_share_pct`,
  `event_income_floor_minor`) ; l'app reçoit `stale_days` par `/finance/settings`.
- Chaque dette porte sa convention de décompte des intérêts (m3) : `act/365` (le défaut, ce
  que le hub faisait pour toutes), `act/360` ou `30/360` (hypothèques). Migration 0025,
  `save_debt.day_count`, choix dans la fiche de la dette.
- `last_used_at` d'un jeton s'écrit au plus une fois par minute (m7) : une requête de
  collecteur ne prend plus le verrou d'écriture pour rien.
- La reprise des règles de l'ancien script sort du hub (m10) : `scripts/legacy_rules.py`, à
  lancer à la main ; la commande `rules import-legacy` disparaît.
- Corrections de lecture d'une transaction crypto à l'arrondi bancaire (m11) ; une seule forme
  de clé (`txid|symbole|jambe`), les bitcoins écrits avant gardent la leur sans doublon. Deux
  opérations IBKR identiques sans identifiant se suivent d'un numéro (m12).
- À date égale, la source d'un cours qui fait foi est déclarée (m13, `assets.PRICE_SOURCES` :
  rapport du dépositaire, relevé saisi, clôture de marché, puis prix d'une opération), plus
  l'ordre alphabétique de son nom ; un type d'instrument connu n'est plus remplacé par une
  autre source ; Yahoo donne le type de ce qu'il cote. Les avis VIAC gardent une clé de
  contenu (un même avis réexporté reste un doublon).
- Le verrou de reprise d'historique expire après 6 h (m14) ; l'export CSV neutralise les
  formules sur toutes les colonnes de texte (m15).
- Compositions de fonds versionnées (m16, migration 0026) : la transparence à une date lit la
  composition connue à cette date ; la table des pays est gelée.
- Les listes de comptes, la fraîcheur et les comptes à rafraîchir se lisent en une requête par
  liste (m17) ; « À classer » et l'historique d'un commerçant lisent les écritures les plus
  récentes, bornées.
- Le planificateur note la dernière minute servie (`scheduler.last` dans les données) et
  rejoue une fois, au redémarrage, chaque job manqué pendant l'arrêt, au plus un jour en
  arrière (m18). Un « oui » à l'assistant ne joue que la question dont il renvoie le jeton
  (`confirm`, relayé par le hub et l'app) ; sans jeton, la voix garde son oui d'une minute.

## [0.13.19] · 2026-11-03

### Finance

- Rapprochement : un fonds dont le relevé arrondit les parts au centième (VIAC) n'est plus une
  rupture pour moins d'un centième de part d'écart entre deux relevés ; une crypto renommée
  (RNDR devenu RENDER, MATIC devenu POL) se compte sous son nouveau nom.

## [0.13.18] · 2026-11-03

### Finance

- Un virement crypto entre deux de mes comptes dont l'arrivée est un peu plus petite que
  l'envoi (frais de retrait, sans txid commun) est reconnu comme virement, même pour le passé :
  plus d'« envoyé hors de mes comptes » ni d'« arrivé de l'extérieur » à régler pour ces cas.
- Cours et cryptos : cours quotidiens CoinGecko pour les cryptos tenues chez SwissBorg (BORG,
  ADA, XRP, TRX, BCH, JitoSOL, Hyperliquid, EigenLayer, Bittensor), dont les cours ne venaient
  que des exports SwissBorg et vieillissaient entre deux.

## [0.13.17] · 2026-11-03

### Finance

- Une transaction crypto relue avec une autre quantité (lecture corrigée, comme le claim de
  Coinbase Wallet) reçoit un mouvement de parts de correction pour la différence : l'écart
  « inexpliqué » qu'elle laissait disparaît, sans réécrire le registre.

## [0.13.16] · 2026-11-03

### Finance

- Cours et cryptos : un portefeuille délégué (EIP-7702, Coinbase Wallet) ne voit plus ses ETH
  reçus annulés par la copie technique `delegatecall` d'un transfert interne ; un claim de
  staking arrive donc bien au portefeuille.
- Une mise en staking et sa sortie (cbwsETH de Kiln brûlés, ETH réclamé) restent à moi : le
  prix de revient ne bouge pas, plus d'envoi ni d'arrivée « hors de mes comptes » à régler, et
  la récompense compte comme gain.

## [0.13.15] · 2026-11-03

### Finance

- Budget : les dépenses classées fixes ou variables d'un compte courant non suivi par le budget
  (l'épargne) comptent maintenant au budget, aux flux, aux totaux et à la tendance. Des impôts
  payés depuis l'épargne entrent dans Impôts ; les intérêts, virements et écritures sans
  catégorie de ce compte restent dehors (#105).

## [0.13.14] · 2026-11-03

### Finance

- Cours et cryptos : un réseau en erreur ne bloque plus l'historique des autres réseaux du
  portefeuille, et l'alerte de l'accueil dit sa cause (clé refusée, explorateur saturé…). Les
  transferts internes de Polygon, que l'offre gratuite d'Etherscan refuse en disant « clé
  invalide », ne font plus échouer tout l'historique (MetaMask, Trust Wallet, Coinbase Wallet).
  Base passe par Blockscout (hors de l'offre gratuite d'Etherscan). L'ETHW a son cours
  (CoinGecko).
- Connexions : les clés d'API se saisissent dans un champ texte masqué ; le trousseau du
  téléphone ne les préremplit plus (il écrasait la clé Etherscan).

## [0.13.13] · 2026-11-02

### Finance

- Patrimoine : un relevé SwissBorg sans cours du jour (valeur 0 pour des parts tenues) ne fait
  plus tomber la ligne à zéro. Elle vaut parts × cours. La Performance des cryptos montrait de
  fausses pertes : environ −2 200 CHF sur l'USDC, et d'autres cryptos SwissBorg touchées.
- Patrimoine : un seul calcul de gain. La Performance des cryptos compte le prix de revient réel
  (commun à tous tes comptes crypto) : un envoi d'un compte à l'autre garde son coût, une
  récompense est un revenu, une vente sort au coût moyen. « Max » = le résultat depuis l'achat.
  La section crypto « Depuis l'achat » disparaît, elle faisait doublon.
- Patrimoine : les soldes qu'aucune opération connue n'explique sont listés, chiffrés, sous le
  grand chiffre et sur l'accueil (`GET /finance/breaks`, règle : docs/finance-politique.md).
  Un écart se règle d'un geste : « J'ai payé X », « Garder tel quel » ou « Parti hors de mes
  comptes ».
  `hub verify` contrôle aussi les chiffres et échoue au-delà de la tolérance.
- Collecteurs : un passage qui saute un réseau faute de clé ou ne trouve pas de cours n'est plus
  « ok » mais « incomplet », avec ce qu'il faut faire sur l'accueil. Les cryptos détenues sans
  cours connu reçoivent les clôtures récentes de Binance.

### Exploitation

- CI plus rapide : les tests tournent en parallèle (pytest-xdist), environ 2 min 30 au lieu de 6.
- Release plus rapide : le tag ne rejoue plus la CI quand celle de main est déjà verte sur le
  même commit (il attend sa fin si elle tourne encore), et les images arm64 se construisent sur
  un runner arm64 natif au lieu de l'émulation QEMU (en release comme dans la CI).

## [0.13.12] · 2026-11-02

### Finance

- Patrimoine : la section « Depuis l'achat » ne plante plus quand une crypto n'est plus tenue
  alors que son historique sort plus de parts qu'il n'en a fait entrer (division par zéro qui
  faisait tomber la page Patrimoine).

## [0.13.11] · 2026-11-02

### App

- Patrimoine : section « Depuis l'achat » quand l'écran ne montre que des cryptos (le filtre
  Crypto), le chiffre à comparer avec CoinStats. Un prix de revient par crypto, commun à tous
  les comptes crypto : un envoi d'un compte à l'autre garde son prix d'achat au lieu de repartir
  au cours du jour, une récompense entre sans coût. Résultat latent et réalisé, en CHF partagé
  entre l'effet des cryptos et l'effet du dollar, ou en USD. La page d'une crypto (tous comptes)
  prend ce prix de revient. Ce que le calcul ne sait pas lire (parts sans historique, arrivées
  d'un compte non suivi) est affiché.
- Patrimoine : un compte à zéro, ou alimenté par sa connexion depuis moins de 45 jours, ne rend
  plus la fin de courbe « estimée » (un compte Revolut qui ne bouge pas n'a pas de solde de
  clôture et gardait une vieille dernière donnée).

### Finance

- « Actualiser » met à jour le solde crypto du jour dans le patrimoine tout de suite (avant :
  le lendemain). Un relevé de plus le même jour ajoute une ligne quand le solde a bougé, une
  crypto sortie du relevé passe à zéro, la plus récente fait foi. Migration finance 0019
  (`holdings` sans la contrainte d'un relevé par jour, lignes et empreintes gardées).

### Assistant

- Le modèle du cloud répond d'abord (section `cloud:`, clé dans `.env`), le modèle local le
  remplace s'il échoue (plus de crédit, clé refusée, réseau, délai), puis 5 minutes de suite.

## [0.13.10] · 2026-10-31

### App

- Patrimoine refait :
  - Net/Brut en haut à droite ; la courbe est simple par défaut, et les puces « Afficher »
    ajoutent les apports, les avoirs et les dettes, le montant visé, les événements (gros
    versements, retraits, revenus) et le plus haut et le plus bas ;
  - courbe datée avec une règle pour mesurer l'écart entre deux dates, et plein écran
    horizontal ;
  - périodes au choix (1M 3M YTD 1A 5A Max épinglées par défaut, dix au total, plus une
    plage libre) ;
  - Gain et Rendement fusionnés en « Performance », en CHF ou en %, avec un repère (le cours
    d'un fonds détenu) ;
  - « Répartir par » un seul panneau : ce qui vient de tes comptes filtre l'écran, le
    contenu des fonds se lit seulement ; filtres Compte et Actif en plus des quatre d'avant ;
  - un compte ou un actif ouvre sa page (courbe, performance, positions ou comptes qui le
    détiennent), avec un chemin en haut et le retour du navigateur ; une donnée périmée ou
    incomplète est signalée sur la courbe.
- Compte : un montant visé, suivi sur sa page avec une projection.

### API

- `GET /api/finance/prices` (cours d'un actif) ; `performance` porte `events` ; `accounts`
  porte `target`. Migration finance 0018 (`accounts.target_minor`).

## [0.13.9] · 2026-10-31

### Collecteurs

- BCF (et VIAC) : l'attente de la validation sur le téléphone survit à une page qui se
  recharge ou à un onglet que la banque ferme ; un essai pris en pleine navigation est refait
  au lieu d'arrêter le run.
- Une erreur imprévue du navigateur dit à quelle étape elle tombe (`statement.link:error`,
  `login.push:error`), avec une capture en mode diagnostic ; jamais son message.

## [0.13.8] · 2026-10-31

### App

- L'accueil n'a plus de bloc Agenda ni de bloc Documents : les rendez-vous et les rappels
  restent dans Rappels et Calendrier, les documents se demandent à l'assistant. Seuls les
  rappels en retard et les entretiens dus remontent dans « À savoir », et la ligne ouvre
  l'assistant.

## [0.13.7] · 2026-10-31

### App

- Finance, retouches de la revue :
  - un écart qui s'arrondit à zéro (« +0 CHF · +0,0 % ») est gris, plus vert ;
  - sur la courbe du patrimoine, le gain est en bleu et la perte en orange, et la légende le
    dit en mots ;
  - les périodes (1M…Max) prennent le même sélecteur segmenté que Valeur/Gain/Rendement ;
  - les filtres du Journal se fondent à droite (la rangée défile) et le filtre choisi est en
    indigo clair ; avec une seule banque, son nom n'est plus répété sur chaque écriture ;
  - Budget : sans budget, « Créer mon budget » est le bouton principal, sous le total ; le
    dernier jour affiche « Dernier jour du mois » au lieu de « 0 jour restant ».
- Réglages : la section du hub (Affichage, Profil, Sécurité, État du hub) passe en premier,
  avant celles des domaines.
- « À valider » ouvre l'accueil : les propositions en attente y sont cochées, avec le bouton
  « Valider N avec Face ID », sans passer par le panneau (« Détails » ou « Tout voir » l'ouvre
  encore, pour les détails et les refus). Elles ne sont plus une ligne de « À faire ».
- L'orbe de l'assistant est au centre de la barre du bas, sur tous les écrans (la même orbe que
  Domia, en WebGL). La toucher ouvre la conversation ; la maintenir écoute (glisser vers le bas
  annule). Hors de la conversation, la réponse sort dans une carte de verre qui reste jusqu'à ce
  qu'on la ferme, et une pastille signale une réponse non lue. L'orbe est grise quand
  l'assistant ne répond pas.
- Le hub relaie l'app vers l'assistant du Mac (`/api/assistant/status`, `history`, `talk`,
  `voice`, session de l'app seule), sans rien garder ; réglage `[assistant] url` (et `person`).
  Caddy autorise le micro pour l'app (`microphone=(self)`) et le son de la réponse (`media-src blob:`).
- La barre du bas ne porte plus que l'accueil et un espace par domaine qui a des onglets :
  « Finance » remplace Patrimoine, Budget et Journal. Dans l'espace, ses onglets sont la barre
  du haut (Patrimoine · Budget · Journal), à côté de l'œil et des réglages, sans titre ;
  l'espace rouvre le dernier onglet vu. Le manifeste d'un domaine donne `label` et `icon`.
- L'accueil n'a plus de barre de titre : une ligne discrète (« Mis à jour… », l'œil, les
  réglages) défile avec lui. On gagne environ 50 px en haut de chaque écran.
- L'accueil est neutre : aucun domaine ne passe plus en tête. « À faire » et « À savoir »
  viennent d'abord, chaque ligne avec le nom de son domaine (« Finance · … »), puis le bloc de
  chaque domaine sous son titre (Agenda, Documents, Finance).
- « Sources et réglages » est rangé par domaine : une section par domaine (Finance : connexions,
  comptes, dettes, export, budget, impôts), puis la section du hub (affichage, profil, sécurité,
  état), au lieu de « Données », « Préférences », « Compte ».
- Les lignes de l'agenda et des documents sur l'accueil ne sont plus coupées après trois lettres :
  sans pastille, leur titre tombait dans la colonne de l'icône. L'agenda n'y liste plus que les
  rappels en retard ou du jour (les autres sont comptés), et un document y porte le nom de sa
  fiche (« Lave-linge », avec le fichier en dessous).

## [0.13.6] · 2026-10-30

### App

- La finance est séparée de la coquille de l'app : ses écrans, ses rubriques, ses styles et
  son accueil vivent dans `hub/domains/finance/web/`, servis sous `/d/finance/` ; de même pour
  l'agenda et les documents. `index.html`, `styles.css` et la coquille ne nomment plus aucun
  domaine, et l'app démarre sans la finance. Des tests tiennent la frontière : la coquille
  n'importe aucun domaine, un domaine n'importe que la coquille et lui-même. À l'écran, rien ne
  change (captures identiques au pixel).
- L'accueil, « À faire », « À valider » et le Face ID appartiennent à la coquille, plus à la
  finance : la finance y pose ses tuiles et ses lignes comme les autres domaines, et une carte
  d'un autre domaine se valide au même endroit, avec un texte neutre (« Rien ne change sans
  ton Face ID ») et le nom de son domaine quand plusieurs domaines attendent.

### Assistant

- Le banc a son propre dossier et ne joint jamais le hub : il avait écrit trois fiches de test
  dans la vraie bibliothèque.

## [0.13.5] · 2026-10-30

### Documents

- Un document peut peser jusqu'à 100 Mo (30 avant) : les notices scannées de la bibliothèque
  (54 et 70 Mo) n'étaient pas reprises.
- Un fichier trop gros est sauté et compté (`too_large`), dans la reprise de la bibliothèque
  comme dans `inbox/documents/` (où il reste), au lieu d'arrêter tout le traitement.

## [0.13.4] · 2026-10-30

### Sécurité

- L'image des collecteurs n'a plus le pip système de sa base Playwright, inutile (uv installe
  tout) : il embarquait certifi 2026.6.17 (GHSA-6q48-6c7w-9gw2, autorités emSign compromises),
  relevé par la barrière de la CI ajoutée en 0.13.3, qui bloquait sa publication. Elle ne
  garde plus non plus de cache (`/root/.cache`).
- Le scan des images de la CI donne le chemin de chaque paquet en faille et passe toujours les
  trois images.

## [0.13.3] · 2026-10-30

### Sécurité

- L'image hub passe à restic 0.19.1 : le binaire de la 0.18.1, compilé avec Go 1.25.1, portait
  deux failles critiques corrigées (grpc CVE-2026-33186, crypto/tls CVE-2025-68121), qui
  bloquaient la publication de 0.13.2.
- La CI des pull requests passe les trois images à la même barrière Trivy que la release
  (critiques corrigeables) : une faille bloque la PR avant le tag, plus une version publiée.

## [0.13.2] · 2026-10-30

### Sécurité

- Les trois images (hub, web, collecteurs) appliquent les correctifs de sécurité des paquets
  de leur base à la construction : brotli-libs (CVE-2026-111497) bloquait la publication de
  0.13.1.

## [0.13.1] · 2026-10-30

### Sécurité

- L'image web passe à Caddy 2.11.7 : la 2.10.2 portait quatre failles critiques corrigées
  (smallstep/certificates, grpc, crypto/tls de Go), qui bloquaient la publication de 0.13.0.

## [0.13.0] · 2026-10-30

### Domaine Documents (chantier S12)

- Les fiches d'objets de la maison et leurs documents (notices, contrats, garanties, courriels)
  dans le hub : un bloc d'accueil (entretiens dus, derniers documents), `/api/documents/…`, des
  outils pour l'assistant qui citent source et page, la recherche et un constat « entretien ».
- Une archive chiffrée dont la base se reconstruit seule (`hub documents rebuild --check`) ;
  un index local des passages (FTS5).
- Un document est privé tant qu'il n'est pas marqué « foyer » (une carte, réversible) ; la
  portée `documents:household` n'ouvre que cette part et les fiches.
- Reprise unique de la bibliothèque de Domia : `hub documents import-library DIR`.

### Domaine Agenda (chantier S11)

- Rappels et Calendrier du Mac dans le hub, par le pont EventKit (`assistant/eventkit`) : un
  bloc d'accueil (la semaine, les rappels ouverts, la liste de courses), `/api/agenda/…`, des
  outils pour l'assistant, la recherche et un constat « rappels en retard ».
- Ajouter un rappel, un événement, cocher : des cartes à valider ; un article sur la liste de
  courses : automatique. Jamais de suppression. Aucune copie dans le hub ; les envois sont
  tracés pour l'idempotence et la réconciliation.
- L'API joint le pont par `host.docker.internal` (`[agenda]` de `deploy/settings.toml`).

### Paliers d'approbation réglables (chantier S11)

- Un type de proposition déclare son palier par défaut (`human`, `auto_digest` ou `auto`) ;
  `hub proposals policy` montre et change les paliers. Un modèle reste à la carte tant qu'il
  ne déclare pas « pas de texte externe ».

### Un seul assistant, venu de Domia (chantier S10)

- L'assistant de Domia arrive dans `assistant/`, avec ses 149 tests, son banc, ses gabarits de
  modèle, ses LaunchAgents et le pont Rappels/Calendrier (`eventkit/`) : un paquet à part, testé
  par sa propre tâche de CI (`make assistant-test`).
- Le contrat avec l'API de Domia est figé dans `assistant/domia_assistant/contract/`
  (`make domia-contract DOMIA=~/domia`).
- L'assistant reprend les outils des domaines du hub (`hub_capabilities`), un type de demande
  par domaine : montrés et ouverts aux seules personnes de `hub.owners` (jamais à Kim ni à une
  voix de pièce), avec le jeton des agrégats ; un domaine lu en entier est écarté.
- Plus de conteneur `brain` : l'assistant tourne en natif sur le Mac et fait aussi le
  classement du matin (`classify`, jeton `brain`, même modèle résident). Les jetons restent
  chiffrés par age (`brain.enc.yaml`). À retirer de `deploy/.env` : `,brain` dans
  `COMPOSE_PROFILES`, `HUB_BRAIN_SECRETS`, `HUB_BRAIN_MODEL`.

### Recherche, liens et constats (chantier S9)

- `/api/search` fusionne les domaines par rang : chaque résultat dit son domaine, son rang dans
  ce domaine et le passage trouvé ; un domaine aux scores plus grands ne prend plus toute la
  page.
- Lier deux objets de deux domaines passe par une carte : type de proposition `core/link`,
  réversible d'un geste (`core/unlink`). `core.db` gagne le journal chaîné, `applied_proposals`
  et `events` (migration `0008_core_ledger`), contrôlés par `hub verify`.
- `GET /api/observations` réunit les constats de chaque domaine ; l'accueil et les liens des
  notifications y lisent les sentinelles de la finance (`/api/finance/alerts` retirée).

### Documentation (chantier S14)

- `vision.md`, `docs/architecture.md` (anneaux, Double Sas, boîte d'entrée, finance en
  sous-contextes, en schémas), `docs/ajouter-un-domaine.md`, `docs/securite.md`,
  `docs/exploitation/` (installation, Mac, versions, kit de secours, gestes réguliers),
  `hub/domains/finance/README.md` ; README réécrit en index.
- Références générées depuis le code : routes de l'API, outils de l'assistant, connecteurs
  (`docs/reference/`, `make reference`). Une référence périmée, un lien relatif cassé, ou une
  recette d'ajout de domaine que le domaine factice ne suit plus font échouer la CI.

### Finance en couches (chantier S6)

- La finance est rangée en quatre sous-contextes (registre, classement, patrimoine, sources),
  chacun en couches interface → app → infra → model ; import-linter les impose sans écart.
- L'importeur, les propositions, les lectures, les outils, la CLI, IBKR, la performance et la
  transparence des fonds sont découpés : plus aucun fichier de la finance au-delà de 400 lignes.
- Imports circulaires cassés : les bords reçoivent `port.Finance`, l'ouverture d'un compte vit
  dans le registre, la lecture des fichiers IBKR et `hub.market.v1` dans `sources/infra`.
- `public.py` : la seule lecture de la finance permise aux autres domaines (agrégats).
- Aucun changement de comportement : mêmes routes, commandes et outils ; une base d'avant,
  reconstruite par `hub finance rebuild`, se compare sans écart.

### App modulaire (chantier S5)

- La coquille de l'app (`shell.js`, `sources.js`) monte les domaines d'après leurs manifestes :
  barre d'onglets, blocs de l'accueil, rubriques de Sources et réglages, actions. La finance
  devient un module comme un autre (`finance.js`, rubriques dans `settings.js`).
- Le manifeste gagne `home` (bloc d'accueil) et `module` (module du domaine) ; un domaine qui
  reprend un écran de la coquille ou d'un autre domaine est refusé au démarrage.
- Écrans identiques à 375 px avant et après (captures comparées, chaque rubrique comprise).

### Sauvegarde et exploitation sans liste en dur (chantier S7)

- `hub ops databases` et `hub ops litestream` : les bases (core, puis chaque domaine monté)
  viennent du registre. `deploy.sh` écrit `deploy/litestream.local.yml` à chaque déploiement
  et le monte dans Litestream ; `deploy/litestream.yml` (le défaut) est vérifié par la CI.
- `restore-test.sh` restaure chaque base de la liste, et plus seulement `core.db`.
- Le contrôle de santé de `deploy.sh` exige `"status":"ok"` (core et chaque domaine monté),
  plus seulement une réponse.
- `deploy/tailscale-acl.hujson` : la politique Tailscale versionnée (seul le propriétaire
  atteint le port 443 du hub).

### Boîte d'entrée par domaine (chantier S4)

- `hub watch-inbox` (service `importer`) confie chaque fichier posé à la racine de `inbox/` au
  domaine qui le réclame (importeurs du manifeste) : il part dans `inbox/<domaine>/`, puis
  chaque domaine traite son dossier (`Domain.process_inbox`). Un fichier réclamé par personne
  reste à la racine ; un nom déjà pris devient `nom-2`.
- Les collecteurs déposent dans `inbox/<domaine de leur connecteur>/` ; le catalogue sait de
  quel domaine vient chaque connecteur.
- L'archive chiffrée de la finance vit dans `archive/finance/` ; la migration déplace une fois
  `archive/AAAA/` et `archive/duplicates/` (les chemins gardés en base restent valables).
- `hub finance watch-inbox` lit désormais `inbox/finance/`.

### Intégrité générique (chantier S3)

- `hub.kernel.chain` (empreinte versionnée, maillon) et `hub.core.integrity` (`Ledger` :
  ajout, vérification, `applied_proposals`, `events`, aides de migration `schema()` et
  `append_only()`) : un domaine neuf a son registre d'ajout seul sans le réécrire.
- La finance s'en sert : `ledger.append` et `ledger.verify` délèguent au cœur, ses champs
  hachés restent dans `hashing.FIELDS`. Même tête de chaîne qu'avant (test de référence).
- Le domaine factice tient ses propositions et événements dans le registre commun ; `hub
  verify` le rejoue.

### Jetons à date de fin, par domaine (chantier S8)

- Chaque jeton a une date de fin (`--days`, 90 par défaut, 366 au plus) ; un jeton fini est
  refusé. Migration `core` 0007 : les jetons existants reçoivent un an depuis leur création.
- `hub token rotate ID` : nouveau secret, mêmes portées, l'ancien révoqué.
- La tâche de nuit prévient par ntfy 14 jours avant la fin, une fois par jeton, avec la
  commande à lancer (pour un service collecteur : recréer son fichier de secrets).
- Le raccourci `brain` n'ouvre plus que les agrégats ; `brain=finance` ajoute lecture et
  propositions des domaines nommés. Les jetons déjà créés gardent leurs portées.
- Les commandes `hub token …` passent dans `hub/cli_tokens.py`.

### Contrat de domaine v2 (chantier S2)

- Manifeste d'un domaine (`hub.core.manifest`) : onglets, cartes d'accueil, rubriques de
  réglages et module des cartes à valider pour l'app ; importeurs (les fichiers de la boîte
  d'entrée qu'il réclame) ; connecteurs ; tables protégées ; consignes pour l'assistant. Les
  constats arrivent par `Domain.observations()` (la finance y verse ses alertes).
- `GET /api/domains` : les domaines actifs et leurs manifestes, pour la coquille de l'app (S5).
  `GET /api/tools` donne aussi les consignes de chaque domaine à l'assistant.
- `HUB_DOMAINS` (`*` par défaut) choisit les domaines montés : un domaine éteint n'a ni base,
  ni route, ni onglet, ni connecteur. Un nom inconnu empêche le démarrage.
- `hub verify` contrôle que chaque table protégée garde ses triggers d'ajout seul.
- Un manifeste invalide (identifiant, module, extension) est refusé à l'enregistrement.

## [0.12.0] · 2026-10-29

### Le cœur ne nomme plus aucune source (chantier S1, seconde partie)

- Le catalogue des connecteurs, les modules par pays (3e pilier en Suisse) et la reprise des
  connexions d'avant G4 passent de `hub/core` à `hub/domains/finance` (`connectors.py`,
  `legacy_connections.py`). Le cœur les lit par trois points d'entrée du paquet
  (`hub.connectors`, `hub.country_modules`, `hub.connection_imports`) via
  `registry.contributions`. Aucun changement de comportement ni de schéma.
- La liaison d'un consentement vaut pour tout connecteur de méthode `open_banking`, plus
  seulement `enable_banking`.
- `tests/test_core_is_generic.py` : un nom de banque, de source ou de notion financière dans
  `hub/core` fait échouer la CI.

### Noyau, plateforme et cœur séparés (chantier S1, première partie)

- `hub/kernel` (argent, URN, horloge, JSON canonique, texte) et `hub/platform` (SQLite,
  migrations, réglages, secrets, journaux, planificateur) sortent de `hub/core`. Déplacements
  seuls, sans changement de comportement ; le lanceur de migrations devient
  `hub.platform.migrations`.
- Import-linter : les étages domaines → cœur → plateforme → noyau ne s'importent que vers le
  bas ; le noyau n'importe aucune bibliothèque d'E/S, la plateforme ni le cœur ni HTTP.

### App web testée et instance d'essai (chantier S13, suite)

- `scripts/demo_data.py` : un an de relevés camt.053 fictifs pour deux comptes, bibliothèque
  standard seulement.
- `tests/web/test_app_mobile.py` : l'app dans Chromium à 375 px, première passkey par un
  authentificateur virtuel, cinq écrans sans erreur ni défilement horizontal ; captures en
  artefact de la CI.
- Lint de l'app par Biome (`biome.json`) et tests des modules par `node --test` (`make web`).
  Deux affectations dans une expression corrigées (`perf.js`, `wealth.js`).
- `deploy/trial.sh` (`make trial`) : instance d'essai jetable, données fictives créées par la
  version en place puis migrées et vérifiées par la nouvelle. `make deploy` la lance avant de
  toucher aux bases ; la CI la lance sur l'image arm64.

### Versions publiées et CI/CD (chantier S13)

- Une seule version, celle de `pyproject.toml` : `hub.__version__` la lit, `/api/health` la
  rend, et l'instantané OpenAPI ne la fige plus. `make release VERSION=X.Y.Z` prépare la PR de
  version (pyproject, `uv.lock`, section du CHANGELOG) ; `make tag` pose le tag sur main.
- Workflow `Release` sur un tag `vX.Y.Z` : barrières de la CI, images linux/arm64 poussées sur
  GHCR avec SBOM et provenance, analyse Trivy, release GitHub avec notes et empreintes.
- `make deploy TAG=vX.Y.Z` tire les images publiées (clone sur le tag, version de l'image
  vérifiée) ; `HUB_BUILD=1` ou un autre tag construit sur le Mac comme avant.
- CI : migration depuis la dernière version taguée sur bases et relevé fictifs
  (`make upgrade-test`), cohérence de la version, `pip-audit` (`make audit`).
- Dependabot : une PR groupée par semaine pour Python, les actions et les images du compose.
- `docs/exploitation/versions.md`, décision D-015.

### Garde-fous du socle (chantier S0)

- Cinq contrats import-linter de plus décrivent l'architecture visée : un noyau pur, une
  plateforme sans métier, un cœur sans FastAPI ni Typer, des modules purs dans la finance, et une
  interface que personne n'importe. Les écarts d'aujourd'hui sont listés dans `pyproject.toml`
  et ne peuvent que disparaître (`unmatched_ignore_imports_alerting = "error"`).
- `tests/test_file_size.py` : 400 lignes au plus par fichier Python ou JavaScript de `hub/` ;
  les 23 fichiers plus longs sont listés avec leur taille, qui ne peut que baisser.
- `tests/test_log_safety.py` : un nom d'événement fixe, aucune clé interdite, jamais `str(exc)`
  dans un journal (5 écarts listés dans les collecteurs). Le filtre refuse aussi `description`,
  `merchant`, `question`, `answer` et `prompt`.
- `docs/glossaire.md` et `docs/decisions.md`.

### Historique des wallets ETH malgré les limites des sources publiques

- Ethereum : historique par Routescan (sans clé) au lieu de Blockscout, qui coupe après dix
  appels. Arbitrum, Base et Polygon : Etherscan V2 avec une clé gratuite (`etherscan_key`,
  champ « Clé Etherscan » dans l'app) ; sans clé, `needs_key` dans le détail, sans échec.
- Chaque réseau est relu en entier une fois (mémoire `<compte>@<réseau>`, `<compte>@solana`).
- Pause entre deux pages d'historique et entre deux cours CoinGecko sans clé ; un refus (429,
  « rate limit ») est réessayé après 10, 30 puis 60 secondes.
- Coinbase : la conversion ETH2 → ETH (`retail_eth2_deprecation`) est interne.
- Réseau BNB Smart Chain (`bsc` : BNB, USDC, USDT, ETH) ; un réseau refusé par l'offre gratuite
  d'Etherscan est signalé (`unsupported`) sans bloquer les autres.
- Portefeuille ATOM (Cosmos Hub) : disponible, staking, retraits en cours, récompenses, et
  historique des transactions.

### Collectes en parallèle

- Les services collecteurs lancent chaque run dans son fil : un run lent (market, 17 minutes
  le 29/10 à cause de mempool.space) ne retarde plus les autres connexions ni leurs
  actualisations. Une connexion n'a jamais deux runs à la fois.

### Un portefeuille crypto s'ajoute dans « Cours et cryptos »

- « Cours et cryptos » (`market`) est une connexion unique (`single`) : en créer une deuxième
  est refusé (`connection.single`), car un portefeuille ajouté ainsi restait sans adresse. Dans
  l'app, choisir ce connecteur quand il existe ouvre ses réglages avec un nouveau portefeuille à
  remplir (« Ajouter un portefeuille »).
- « Nom affiché de la connexion » : le nom de la connexion, pas celui d'un portefeuille.

### Actualiser une connexion depuis l'app

- « Actualiser » sur chaque connexion et « Tout actualiser » (Réglages › Connexions) : un run
  complet hors horaire, lancé dans la minute par le service collecteur (`POST
  /api/collectors/<id>/refresh`, `POST /api/collectors/refresh`). Seulement pour une connexion
  prête et active (`collector.not_enabled` sinon). La ligne montre « actualisation en cours »,
  puis l'issue et l'heure du dernier passage ; l'app relit ses chiffres après l'import.
- Les limites des sources restent dans les flux : push BCF à valider, quatre synchros par jour
  pour Enable Banking (« quota du jour atteint »).
- Horaires par défaut : cours, portefeuilles et plateformes crypto toutes les 4 heures de 06:15
  à 22:15 (au lieu d'une fois par jour).
- Migration core `0006_collector_refresh` (`collector_state.run_requested_at`).

### Écritures crypto natives pour chaque connecteur

- Règle : un connecteur crypto apporte ses écritures, pas seulement ses soldes. `runner(fetch,
  history)` exige une lecture d'historique et un test refuse un connecteur crypto ou une chaîne
  de portefeuille qui n'en a pas.
- Coinbase : transactions de tous les portefeuilles (achats, ventes, conversions, envois avec
  frais de réseau, récompenses, virements), à la valeur donnée par Coinbase.
- KuCoin : grand livre par tranches de 24 heures, un an (ce que KuCoin garde).
- Portefeuilles ETH (Blockscout, jetons suivis et gaz) et SOL (RPC) : leurs transactions au
  registre, reliées aux plateformes par le txId. Le solde passé n'est pas reconstitué.
- Portefeuille ETH multi-réseau : `networks` (Ethereum, Arbitrum, Base, Polygon), soldes et
  historique sur chacun ; cases « Réseaux » dans l'app. Jetons de staking (`staking_tokens`,
  Kiln cbwsETH) comptés comme de l'ETH à leur valeur sous-jacente.
- Socle commun `exchanges/history.py` ; une jambe d'opération peut porter sa valeur
  (`value`, `value_currency`).

### Binance : récompenses Earn relues

- Les historiques de récompenses Simple Earn refusent une période de plus de 30 jours
  (`-6021`) : fenêtres de 29 jours. Les récompenses manquées depuis la v0.9.9 sont relues une
  fois depuis la première opération (mémoire `rewards_since`, `first_day`).

### Dettes dans le patrimoine : crédit, hypothèque, leasing, prêt étudiant

- Nouvelles tables `debts` et `debt_balances` (migration `0016_debts`). Une dette part d'un
  solde à une date, ou du versement reçu du prêteur choisi dans le Journal (« Créer une dette
  depuis ce versement »).
- Son solde baisse de chaque paiement de sa catégorie (depuis son compte s'il est choisi), quel
  que soit le montant : une mensualité qui change suit d'elle-même. Intérêts courus au taux
  annuel s'il y en a un ; un relevé du prêteur (`record_debt_balance`) remplace le calcul à
  partir de sa date. Mensualité et échéance facultatives : sans mensualité, la fin projetée suit
  les derniers paiements. Une dette se marque soldée ou se rouvre.
- Le patrimoine est net : enveloppe `dettes`, clé `debt:<id>` dans `by_account`, ligne « Dettes »
  dans l'écran Patrimoine (détail : remboursé, paiements, fin projetée). Un remboursement compte
  comme versement, seuls les intérêts font baisser le patrimoine. `GET /finance/debts`, carte
  « Dettes » dans les réglages, propositions `save_debt` et `record_debt_balance` (Face ID).

### Diagramme de flux du budget plus lisible

- Les flux ne se croisent plus : revenus (du plus gros au plus petit) et groupes sont empilés dans le même ordre, et chaque revenu remplit les groupes dans l'ordre Fixes, Variables, Épargne, Reste. Un petit revenu (remboursement) ne s'étale plus en filets vers tous les groupes.
- Une couleur par groupe, de la source jusqu'aux postes : flux, barre du groupe et barres de ses postes. Les Fixes passent en bleu pour ne plus ressembler au Reste gris (même couleur dans l'historique des mois).
- Toucher un revenu n'allume que les groupes et postes qu'il alimente vraiment.

### Historique Binance dans le Journal, mouvements crypto reliés entre mes comptes

- Le collecteur Binance lit, en plus des soldes, les dépôts et retraits crypto (txId, adresse),
  les virements en monnaie, les achats par carte, les ordres exécutés, les conversions, les
  récompenses Simple Earn, les distributions et les petits soldes convertis en BNB
  (`binance_history.py`). Premier passage complet ou rien, ensuite trois jours de recouvrement.
- Ces opérations deviennent des écritures du compte `crypto:binance` en devise de base, codes
  `EXCHANGE/…` (règles système, migration `0015_exchange_journal`), et des mouvements de parts
  (`exchange.py`). Clôtures Binance et change BCE déposés avec l'historique.
- Un envoi ou une arrivée crypto est relié à l'autre côté sur un autre de mes comptes (Ledger,
  Binance, SwissBorg) par le txId, sinon la quantité, à cinq jours près (`links.py`) : le second
  prend la valeur du premier et la paire passe avant les autres virements.

### Budget proposé par l'assistant, au mois ou à l'année

- `finance_propose_budget` prend `cadence` (`month` par défaut, ou `year` : `amount` est alors
  la cible annuelle, suivie en cumul depuis janvier). Un budget complet se propose d'un coup et
  se valide d'un seul Face ID.

### « À classer » : dépenses et entrées à confirmer séparées

- En tête de « À classer », un sélecteur « À classer / À confirmer » (avec leur nombre) montre
  soit les écritures sans catégorie, soit celles classées d'office par la règle « tout le
  reste », au lieu de les mettre bout à bout.

### Achats uniques : une carte par catégorie

- `categorize_entries` : une catégorie pour quelques écritures choisies (30 au plus), une seule
  carte. L'outil `finance_propose_categories` la propose (16 outils Finance) ;
  `finance_to_review` prend `offset` pour parcourir toute la file.
- IA locale : `hub-brain direct` classe les commerçants vus une seule fois, sans créer de
  règle ; les cartes se déplient dans « À valider » pour décocher une écriture.
- `HUB_PROPOSALS_PER_HOUR` (deploy/.env) règle la limite de cartes par heure et par jeton ;
  `catchup --limit` va au-delà de 50 quand elle est relevée.

### Classer plus vite : commerçant lu dans le libellé, revenus à confirmer, rattrapage par l'IA

- Les paiements par carte BCF (« Paiement jj.mm.aaaa hh:mm COMMERÇANTVILLE Numéro de carte… »,
  l'ancien format « Paiement - COMMERÇANT, VILLE - … », Maestro, remboursements), les retraits
  et TWINT n'ont pas de vraie contrepartie : le commerçant est lu dans le libellé (ville et
  numéro de magasin coupés, `merchant.py`). « À classer » groupe par commerçant au lieu d'un
  groupe par achat, l'écriture le donne (`merchant`) comme titre et motif de « Toujours ».
- Un crédit classé par la règle « tout le reste » (« Autres revenus ») revient dans « À classer »
  sous « À confirmer » (`guess` dans `/finance/review`).
- `categorize_rest` : les dépenses encore sans catégorie d'avant une date prennent une catégorie
  d'un coup (« Classer d'un coup tout l'ancien… »).
- « Toujours » peut se limiter au compte de l'écriture (« Seulement depuis ce compte ») ; la
  règle seule est proposée quand elle classe aussi l'écriture, ce qui évitait « a changé
  entre-temps ».
- Packs v2 : `base` reconnaît le salaire par le code bancaire `PMNT/RCDT/SALA`, ajoute
  « Intérêts et dividendes », « Ventes d'occasion », « Aides et allocations » et « Divers » ;
  `ch` connaît plus d'enseignes. « À classer » propose la mise à jour (`install_pack`).
- IA locale : `hub-brain catchup` propose une règle par commerçant de la file (50 au plus, sous
  la limite de 60 propositions par heure), à valider ensemble dans « À valider ».
  `finance_propose_rule` prend `direction` ; ses règles ont la priorité 10.

### Poches Revolut : virement reconnu après une recharge du même montant

- Quand la BCF recharge le compte Revolut puis que l'argent part le jour même vers une poche,
  le même montant apparaît deux fois en débit et l'appariement renonçait. Les paires compte ↔
  poche (même établissement, un jour d'écart, seuls candidats entre eux) sont maintenant
  trouvées d'abord, et ce qu'elles expliquent ne rend plus la recharge BCF ambiguë.

### Poches et enveloppes : virements, règle d'un compte, budget annuel

- Les mouvements entre deux comptes du même établissement (le compte Revolut et ses poches),
  de même montant, à un jour d'écart au plus et sans autre candidat, sont appariés comme
  virements, même sans IBAN ni code de virement.
- Un virement apparié passe avant une règle « tout le reste » (motif vide, comme « tout crédit
  restant → Autres revenus ») : il est montré et compté comme « Virement entre mes comptes »
  (vue `v_entry_shown`, migration finance 0014). Une catégorie choisie ou posée par une règle
  précise reste la sienne. Les deux côtés quittent aussi « À classer ».
- Règle d'un compte (`create_rule` avec `account_id`, motif vide permis) : dans les réglages
  d'un compte, « Dépenses de ce compte » range toutes ses sorties dans une catégorie (une poche
  Vacances), celles déjà importées comme les prochaines. `/finance/accounts` donne
  `spend_rule`.
- Budget annuel : `set_budget` accepte `cadence` (`month` ou `year`, table `budget_cadence`).
  Une catégorie suivie à l'année est comparée au cumul depuis janvier (`yearly` dans les lignes
  du budget), sort du budget et du reste à vivre du mois (`budgeted_expenses`) et n'alerte
  qu'au dépassement annuel. Dans l'app : « Par mois / Par an » dans la fiche d'une catégorie.
- Catégories « Voiture : crédit » (fixe) et « Voiture : frais » (variable : entretien, assurance, impôt et vignette).

### Mois budgétaire, création du budget et journal revu

- Réglage « Le mois commence le » (1 à 28, `GET/POST /finance/settings`, table
  `budget_period` dans la migration 0013) : budget, flux, tendance, projection, sentinelles et
  outils découpent les mois à partir de ce jour. Après le 15, le mois porte le nom de sa fin.
  Le Budget affiche alors les dates exactes sous le mois.
- « Créer mon budget » : une cible par catégorie de dépense, proposée d'après la moyenne des
  3 derniers mois et arrondie à la dizaine, modifiable, validée en une fois avec Face ID.
- Journal : panneau de filtres (compte, catégorie, période, montant), tri par plus gros
  montant, puces des filtres actifs ; la recherche se combine aux filtres et se pagine
  (`/finance/entries` accepte `min_minor`, `max_minor`, `q`, `sort`).
- « À classer » : chaque groupe montre ses comptes, ses dates, la fourchette des montants et
  les libellés bancaires, et se déplie sur ses dernières écritures.

### Comptes : fraîcheur juste et réglages dans l'app

- La fraîcheur d'un compte vient de sa dernière donnée (écriture, position, ordre ou solde de
  clôture) et de son dernier import, y compris pour les comptes sans relevé bancaire (Revolut,
  SwissBorg, Ledger, titres) et les sous-comptes IBKR. « Comptes à rafraîchir » de l'accueil
  suit la même règle et ignore les comptes jamais alimentés ou masqués.
- Réglages d'un compte, validés avec Face ID (proposition `edit_account`, migration finance
  0013) : nom, objectif, disponibilité, catégorie imposée à tout le compte, masquage. Un compte
  masqué sort du patrimoine et de l'accueil, sans rien effacer. La carte « Comptes » des
  réglages liste la fraîcheur et ouvre ces réglages ; le détail d'un compte aussi.

### Construction des images plus rapide

- Les images hub et collector ne copient plus `hub/web` : une retouche du front ne
  reconstruit que l'image web. Seul le paquet hub est recompilé en bytecode à chaque
  version, plus tout l'environnement Python.
- `make deploy` ne finit plus en erreur sur macOS : une apostrophe dans `${…:-…}` cassait
  le bash 3.2 du Mac après le déploiement.

### Hub générique, G6 — première installation

- `make init` (`hub init` dans un conteneur jetable, seul Docker requis) : clé age en 0400,
  `secrets.enc.yaml` avec un mot de passe restic tiré au hasard et jamais affiché, dossiers
  montés, `deploy/.env` écrit depuis `.env.example`. Ne remplace rien de ce qui existe.
- `HUB_COUNTRY` : pays d'une instance sans profil, qui choisit le pack de règles d'une base
  neuve (CH par défaut, rien ne change pour une instance existante).
- Le premier `make deploy` affiche le code d'inscription de la première passkey.
- App : carte « Premiers pas » sur l'accueil (passkey de secours, profil, règles, première
  connexion, premier compte), qui remplace le texte « Pas encore de données ». Les packs de
  règles du pays s'installent par une proposition `install_pack` validée avec Face ID ;
  `GET /api/finance/rules/packs` les liste.
- Guide générique [docs/exploitation/installation.md](docs/exploitation/installation.md) ; `docs/exploitation/mac.md` reste pour ce
  qui est propre au Mac.

### Cryptos au registre — SwissBorg et portefeuille BTC

- Chaque ligne du relevé SwissBorg devient une opération du compte `crypto:swissborg` en CHF
  (dépôt, retrait, achat, vente, rendement, frais) et un mouvement de parts : prix de revient,
  rendements et frais comme pour IBKR. Codes `SWISSBORG/…` déclarés dans `institutions`,
  règles système par la migration `0011_crypto_journal`. Le coût d'une crypto vient de ses
  opérations quand il y en a, sinon de la valeur à l'arrivée.
- Portefeuille BTC : le collecteur `market` dépose ses transactions (toutes au premier passage,
  mémoire `btc_txs`, ensuite la dernière page de chaque adresse) ; chacune devient une
  opération du compte (`CRYPTO/RECEIVE`, `CRYPTO/SEND`, `CRYPTO/FEE`) et un mouvement de
  parts. Une arrivée de la quantité nette d'un retrait SwissBorg prend sa valeur et s'apparie
  avec lui comme un virement entre mes comptes.
- `fin imports replay <source>` : réapplique depuis l'archive les documents déjà importés d'une
  source après une évolution de l'importeur.

### Hub générique — G5 : écrans Connexions et Comptes

- Onglet Sources, carte **Connexions** (remplace « Collecteurs ») : ajouter une connexion du
  catalogue, régler son nom, son horaire, ses réglages et ses portefeuilles, remplacer ses
  identifiants (chiffrés à la saisie, jamais réaffichés), la retirer. Désactiver, Réactiver et
  Contrôler restent.
- Consentement Enable Banking depuis l'app : `POST /api/collectors/{id}/link` ; le service
  `collector-api` ouvre l'autorisation dans la minute, dans un fil à part, et remonte l'adresse
  (`PUT /api/collectors/{id}/link-url`, portée `collector`) que l'app affiche ; la liaison est
  déclarée comme un contrôle. Migration core `0005_collector_link`.
- Portefeuilles crypto : réglage `wallets` de la connexion `market` (adresses et clés
  publiques, vérifiées, clé privée refusée) au lieu des secrets ; `hub connections import`
  (donc `make deploy`) les sort des secrets une fois. La clé CoinGecko reste un secret.
- Carte **Comptes** : comptes attendus par des relevés (`GET /api/finance/accounts/pending`,
  sans montant), portefeuilles et plateformes sans compte, créés par une proposition
  `create_account` validée avec Face ID. Un compte Revolut s'ouvre au solde déduit de sa
  reprise. `/api/finance/accounts` donne `external_ref`.
- Les fichiers de l'app sont servis en `Cache-Control: no-cache` et le service worker recharge
  sa copie depuis le serveur : après un déploiement, Safari ne mélange plus un ancien module et
  un nouveau (l'app restait sur « Chargement… »).
- Notifications et page de retour renvoient vers l'app au lieu du terminal.

### Hub générique — G4 : connexions en base, deux services collecteurs

- Ce que l'instance collecte est une liste de connexions dans `core.db` (migration
  `0004_connections`) : connecteur du catalogue, identifiant, nom, horaire, réglages sans secret
  et secrets chiffrés par age vers la clé de la machine. L'API les chiffre à la saisie et ne les
  relit jamais ; seul le service collecteur qui exécute la connexion les déchiffre, au run.
- Les huit conteneurs collecteurs deviennent deux services, `collector-browser` (BCF, VIAC) et
  `collector-api` (le reste), qui demandent chaque minute leurs connexions prêtes au hub
  (`GET /api/collectors/runner/{service}`, portée `collector`). Plusieurs connexions d'un même
  connecteur sont possibles (deux banques par Enable Banking, par exemple).
- Le connecteur « revolut » devient `enable_banking` (réglages `aspsp_name`, `aspsp_country`…) ;
  la connexion existante garde l'identifiant « revolut », donc son URL de retour et son état.
- `hub connections list|catalog|add|set|secrets|remove|import` et, pour l'app,
  `GET|POST /api/collectors/connections`, `PATCH …/{id}`, `PUT …/{id}/secrets`,
  `DELETE …/{id}`. `hub connections secrets ID --file -` lit un YAML sur l'entrée standard.
- `hub-collector run|relogin|link|aspsps|consent <connexion>` ; `hub-collector revolut
  link|aspsps|status` reste.
- Reprise automatique par `make deploy` : la migration crée une connexion par collecteur connu,
  `hub connections import` reprend les secrets des `<nom>.enc.yaml` (sans l'ancien jeton) et les
  horaires de `[collectors] schedules`, écrit les fichiers et jetons des deux services, et les
  anciens volumes sont recopiés dans ceux des services. Les anciens jetons restent valides pour
  un retour arrière ; à révoquer une fois la version validée.
- `[collectors] schedules` n'est plus lu au run : les horaires vivent dans les connexions.
- Limite connue : l'importeur Finance des fichiers Enable Banking reste au format Revolut
  (`hub.revolut.v1`, comptes `revolut:`) ; une autre banque demandera son adaptation.

### Hub générique — G1b : devise de base

- La devise de base vient de `HUB_CURRENCY` (CHF par défaut), posée par compose comme `HUB_TZ`
  et lue par `hub.core.money.base_currency()`. Valorisation, instantanés, chiffres clés,
  budgets, outils de l'assistant, cours du collecteur « market » (BCE et CoinGecko dans cette
  base, le franc compris) et app l'emploient au lieu du CHF codé en dur.
- Migration `0010_base_currency` : la devise est fixée dans `finance.db` à sa création ; une base
  qui a déjà des écritures reste en CHF. Si `HUB_CURRENCY` ne la suit plus, la migration échoue
  avec un message clair et `/api/health` signale `currency_mismatch`.
- Le profil (`/api/profile`) donne `currency` ; l'assistant écrit ses montants dans cette devise.
- L'outil `finance_propose_budget` prend `amount` ; l'ancien `amount_chf` reste accepté.

### Hub générique — G2 : packs de règles

- Les règles de départ ne viennent plus des migrations mais de packs YAML versionnés
  (`hub/domains/finance/packs/`) : `base` (mots génériques, services internationaux) et `ch`
  (commerces et prestataires suisses), découpés du fichier de départ de l'ancien script sans
  ses lieux personnels (bars et administrations de Fribourg, comptes Revolut et Raiffeisen).
- Une base neuve reçoit `base` et le pack du pays du profil ; `0004_rules` n'y installe plus
  que les catégories et `0008_crypto_cost` n'a plus rien à faire. Une base existante garde ses
  règles `seed-` et n'a aucun pack installé. Migration `0009_rule_packs` (version installée de
  chaque pack), recopiée par la reconstruction.
- `fin rules packs list|install [--dry-run]` (nom de pack ou fichier `.yaml`) et
  `fin rules export FICHIER [--origin user…]` : les règles personnelles se sortent au format
  d'un pack et se réinstallent ailleurs. Une règle de même forme n'est jamais doublée, une
  règle de pack désactivée le reste, une nouvelle version désactive ce qu'elle retire.
- `legacy.DEFAULT_RULES` quitte le code ; `import-legacy` reprend toujours un `bcf_rules.json`.

### Hub générique — G3 : catalogue de connecteurs

- `hub/core/connectors.py` déclare une fois chaque connecteur : méthode (`open_banking`, `api`,
  `public`, `browser`), pays, types de comptes, champs de secrets, horaire par défaut, sources
  d'import. Les listes du cœur (`COLLECTORS`) et des conteneurs (`NAMES`) et les horaires par
  défaut en sont tirés ; `[collectors] schedules` ne remplace plus que les horaires qu'il nomme.
  Route `GET /api/collectors/catalog` (app). Des tests vérifient que compose, le code des
  collecteurs (secrets lus) et le planificateur suivent le catalogue.
- `hub/domains/finance/registre/model/institutions.py` déclare les codes d'opération VIAC et IBKR et leur rôle
  (virement, mouvement interne, effet marché, versement 3a) ; l'appariement, la valorisation et
  le suivi du 3a les lisent au lieu de listes écrites en dur. Un test vérifie qu'ils concordent
  avec les règles système des migrations. Aucun changement de résultat.

### Hub générique — G1 : profil de l'instance

- `core.db` (migration `0003_profile`) : profil de l'instance, prénom et pays. Une base existante
  reçoit la Suisse, sans prénom. Routes `GET /api/profile` (app et jetons de lecture) et
  `POST /api/profile` (app seulement), carte « Profil » dans Sources, `hub profile show|set`.
- Le pays ouvre les modules qui lui sont propres : le pilier 3a (chiffres clés, outil
  `finance_networth`, alerte de fin d'année) ne s'affiche plus hors de Suisse.
- Fuseau de l'instance : `HUB_TZ` (Europe/Zurich par défaut), posé par compose dans tous les
  conteneurs, remplace les fuseaux de Zurich écrits dans le code (jour civil des chiffres,
  horaires des collecteurs et du planificateur, navigateur des robots, dates de l'app).
- Assistant : le prénom et le pays viennent du profil (`GET /api/tools` le renvoie) ; plus aucun
  prénom dans le code, les prompts ni l'exemple `deploy/.env`.

### Cryptos automatiques

- Collecteur `market` : un portefeuille BTC peut se donner par sa clé publique étendue (`xpub`,
  `ypub`, `zpub`) ; ses adresses de réception et de monnaie sont dérivées dans le conteneur
  (embit), jusqu'à 20 adresses vides de suite, sur les quatre types d'adresse pour une `xpub`.
  Une clé privée est refusée.
- Ethereum : jetons USDC et USDT en plus de l'ETH (`erc20_tokens`). Solana : SOL et jetons USDC,
  USDT (`spl_tokens`) par le RPC public. Plusieurs chaînes peuvent alimenter un même compte.
- Un compte dont une adresse ne répond pas est laissé de côté en entier ce jour-là (détail
  `partial wallet.<nom>:…`) ; un portefeuille vide donne un relevé à zéro.
- Collecteurs `binance`, `kucoin` et `coinbase` (API officielles, clés en lecture seule, un
  conteneur et un fichier de secrets chacun) : soldes de la plateforme vers `crypto:<plateforme>`.
- Cours CoinGecko par défaut : SOL, USDC et USDT en plus de BTC et ETH.
- Performance des cryptos (Finance) : `GET /finance/holdings` porte un bloc `crypto` (investi =
  paiements nets de la catégorie « Crypto », valeur, résultat) et un prix de revient par crypto
  (valeur à l'arrivée sur le portefeuille). Les paiements « Crypto » ne comptent plus comme
  sortie du patrimoine. Migration `0008_crypto_cost` : règles de départ KuCoin, Bitpanda,
  Bitstamp, Crypto.com, Bitvavo, Bybit, Pocket Bitcoin, Bitcoin Suisse et Mt Pelerin.
- Historique BTC : au premier passage, le solde de chaque jour où il a bougé est relu sur la
  chaîne (transactions des adresses utilisées) et déposé en relevés passés. Avant la fenêtre
  d'un an de CoinGecko, change BCE et clôtures publiques Binance (USD) pour le valoriser.
- Relevé SwissBorg (`.xlsx`, Profil → Documents → Relevé de compte) : soldes par actif rejoués
  depuis le premier mouvement, un relevé de positions de `crypto:swissborg` par jour où ils
  bougent, cours et change USD/CHF tirés du fichier. La boîte d'entrée et l'import de l'app
  acceptent les `.xlsx` (lecteur interne, première feuille, texte des cellules).
- mempool.space : une seconde entre deux adresses BTC, et sur un refus 429 un nouvel essai après
  10, 30 puis 60 secondes (une liste de 48 adresses était coupée après une vingtaine).

### Lot 7 — IA locale

- Outils de l'assistant : contrat `McpTool.call(args, caller)` (le cœur fournit les portées et
  la création de propositions), routes `GET /api/tools`, `GET /api/tools/{domaine}`,
  `POST /api/tools/{domaine}/{outil}`, réservées aux jetons. Une portée `aggregates` est ouverte
  à la portée `read` du même domaine.
- Les 15 outils Finance du plan : catégories en liste fermée dans le schéma, montants en CHF à
  deux décimales, aucun IBAN, `data_as_of` dans chaque réponse, libellés marqués comme texte
  externe. Le jeton « agrégats » n'a que 7 outils de totaux ; une catégorie ou un mois de moins
  de 3 écritures y est fondu ou masqué.
- Propositions d'un jeton limitées par heure glissante (`auth.token_proposals_per_hour`, 60).
- Sentinelles de nuit (schéma `0007_alerts`) : budget dépassé ou qui va l'être, abonnement en
  hausse, marge 3a pas encore versée en novembre et décembre. Une alerte par occasion, notifiée
  par l'événement `notify.request` (texte générique, ni montant ni nom), route
  `GET /api/finance/alerts`, lignes dans « À traiter ».
- Brain (`hub/brain`, commande `hub-brain`, conteneur `brain` au profil compose « brain ») :
  passerelle MCP sur stdio sans dépendance, routage des outils par domaine
  (`hub_capabilities`, `hub_load_tools`), assistant `ask` sur Ollama par l'API compatible
  OpenAI (MLX possible par la configuration), suggestions de catégorie pour les commerçants
  jamais vus (`suggest`, chaque matin), contrôle de bout en bout `check`.
- App : la raison d'une proposition de l'assistant s'affiche sur sa carte.

### Lot 6 — Patrimoine complet

- Schéma `0006_wealth` : instruments élargis (cryptos, symboles, sorte), compositions des fonds,
  tables dérivées `transfer_links` et `recurring`, vue d'allocation (un virement apparié compte
  comme `transfer-own`), devises supplémentaires, règles système `IBKR/…`.
- IBKR : relevés Flex Query (comptes de liquidités par devise créés au premier relevé, achats,
  ventes, change, commissions, dividendes, positions, cours, soldes de fin comme points de
  contrôle), dédoublonnage par `transactionID`, `fin ibkr add-account` et `import-history`.
- Valorisation multi-devise : comptes et positions convertis en CHF au dernier cours connu ;
  l'enveloppe `ibkr` devient `titres`.
- Fichiers `hub.market.v1` (change BCE, cours, soldes crypto), CSV de positions saisies à la
  main (placements Revolut), compositions de fonds (listes d'émetteur ou CSV générique) ; `fin
  crypto add-wallet`, `fin positions add-account`, `fin derived`.
- Virements appariés (IBAN, référence, montant), abonnements récurrents avec prochaine
  échéance ; routes `lookthrough`, `recurring`, `transfers` ; `kpis.unmatched_transfers`.
- Collecteurs `ibkr` (Flex Web Service) et `market` (BCE, CoinGecko, mempool.space, nœud
  Ethereum, Yahoo facultatif), sans navigateur ; services compose correspondants.
- App : enveloppe Titres, positions de toutes les enveloppes, carte Transparence, carte
  Abonnements, virements sans autre côté dans « À traiter », comptes en devise affichés avec
  leur devise.
- Reconstruction : les documents du lot 6 se rejouent ; `compare` couvre change,
  compositions, virements appariés et abonnements. Raiffeisen (camt.053) couvert par un test.

### Lot 5 — Collecteurs

- Cœur : schéma `0002_collectors` (type de passage, contrôle demandé, liaisons), table des
  échecs de la section 8 (suspension, alertes, retour manuel après un contrôle réussi),
  alertes ntfy génériques, routes `/api/collectors` (état, passages, mode, contrôle, liaison
  Revolut et page de retour), purge nocturne des liaisons.
- Paquet `hub.collectors` (image `collector`, Chromium de Playwright 1.63) : dépôt atomique
  dans la boîte d'entrée avec contrôle de forme et quarantaine, sélecteurs nommés et liste
  blanche de clics, captures `--diagnose` purgées après 7 jours, boucle planifiée.
- Bot BCF (camt.053 depuis J-10, validation push de 3 min, refus détecté tout de suite) et bot
  VIAC (liste Documents, avis nouveaux, rapport tous les 6 jours, `relogin` avec code 2FA tapé
  dans le conteneur), sélecteurs repris des scripts du Mac.
- Revolut par Enable Banking : JWT RS256, liaison avec reprise complète dans la fenêtre de
  5 minutes, au plus 4 synchros par jour, alerte avant la fin du consentement.
- Finance : import des JSON Enable Banking et du CSV Revolut (comptes `revolut:<devise>`,
  ouverture au solde déduit), `fin revolut pending` et `add-account`.
- App : carte Collecteurs dans l'onglet Sources (désactiver, contrôler, réactiver).
- Compose : services `collector-bcf`, `collector-viac`, `collector-revolut` (profil
  `collectors`, un volume et un fichier de secrets chacun) ; l'API lit le sujet ntfy ; CI :
  Chromium pour les tests, image collecteur.

### Lot 4 — VIAC et patrimoine minimal

- Schéma `0005_viac` : instruments, opérations (`trades`), positions (`holdings`) et cours
  (`prices`) en ajout seul et chaînés au journal, `rebuild_meta`, catégories `transfer-titres`,
  `rendement` et `frais-placement`, règles système des codes `VIAC/…`.
- PDF VIAC : `pdftotext -layout` isolé (processus séparé, délai, mémoire et taille plafonnés,
  rien sur le disque), parseurs des avis (achat, vente, dividende, intérêts, commission,
  versement, retrait) et du rapport portés de `viac_parser.py` et `viac_rapport.py` ;
  attestations et relevés reconnus et ignorés, le reste refusé.
- Deux comptes par portefeuille (liquidités 3a et titres) ; boîte d'entrée et dépôt par l'API
  acceptent les `.pdf` ; `hub finance viac add-portfolio` et `viac import-history`.
- Valorisation des titres par positions et cours, versements nets hors rendement et frais
  (l'effet marché n'est plus nul), marge 3a d'après les versements VIAC, valeur de marché dans
  `accounts`, route `holdings`, carte Positions dans l'onglet Patrimoine.
- `hub finance rebuild` (reconstruction du registre par rejeu, nouvelle époque du journal) et
  `hub finance compare`.
- Image et CI : poppler-utils.

### Lot 3 — Catégories et Double Sas

- Moteur de règles (`0004_rules`) : la règle active la plus prioritaire gagne, appliquée à
  l'import et par `hub finance rules run` ; une catégorisation humaine n'est jamais remplacée.
  Les règles et catégories de `bcf_aggregate.py` sont reprises (`seed-`), et
  `hub finance rules import-legacy` reprend le fichier de règles du Mac ; mêmes catégories que
  le script sur les relevés fictifs.
- Double Sas côté cœur : défi WebAuthn qui porte l'empreinte du lot (`/approvals/challenge`),
  validation par lot (`/proposals/accept`), revendication par révision, empreinte revérifiée
  sous le verrou d'écriture (nouvelle révision et 409 si elle a changé), aucun double effet
  même si le COMMIT échoue, inverse d'un geste (`/proposals/{id}/revert`), résumé du jour
  (`/digest`), paliers `human`, `auto_digest`, `auto`.
- Handlers Finance : `recategorize`, `create_rule`, `disable_rule`, `set_budget`, `add_note`,
  `apply_import` (relevé en attente à forcer), `create_account`, `create_category` ; le CLI
  comptes et catégories passe désormais par une proposition.
- `hub proposals list|show|accept|reject|create`.
- App : carte « À valider » (un Face ID pour le lot), « À catégoriser » groupé par
  contrepartie dans le Journal, avec « Ces N écritures » et « Toujours » (règle).
- Correctif : après la première connexion, la barre d'onglets restait vide jusqu'au
  rechargement.

### Lot 2 — App en lecture

- Instantanés du patrimoine (`0003_snapshots`) : une ligne par fin de mois et une pour
  aujourd'hui, recalculées par la tâche de nuit et par l'événement `import.applied` (curseur
  dans la boîte de sortie) ; la série stockée égale le calcul direct.
- Routes de l'app : `kpis`, `networth/history`, `flows`, `budget/totals`, `budget/months`,
  `export.csv` ; `budget` prend `period=m|q` et rend reste à vivre et jours restants. Mois
  toujours en paramètre, début d'année au 31 décembre, rapports en décimales texte.
- Écritures sans catégorie comptées en dépense variable (débit) ou en revenu (crédit) dans
  le résumé, le budget et la tendance, en attendant les règles du lot 3.
- Port du dashboard : d3 7.9.0 servi par le hub, `store.js` à la place du runtime `dash.*`,
  CSS et JS en fichiers (CSP stricte respectée), vues Accueil, Patrimoine, Budget, Journal
  et Sources, bandeau « relevé du … », comptes périmés et écrans sans donnée.

### Lot 1 — Registre BCF

- Base `finance.db` (`0001_ledger`, `0002_fts`) : comptes, imports et relevés, registre
  `entries` en ajout seul, catégories et règles, catégorisations et ventilations, notes,
  checkpoints, budgets, tags, `applied_proposals`, `events`, `fx_rates` (vide au lot 1).
  Journal chaîné commun à toutes les tables protégées et empreintes versionnées (`hash_v`).
- `ledger.append()` dans `BEGIN IMMEDIATE`, identifiant d'écriture déterministe,
  `hub finance verify-ledger`, branché sur `hub verify` et la tâche de nuit.
- Fabrique de relevés camt.053 .04 et .08 fictifs, valides contre les XSD ISO 20022.
- Parseur durci (lxml sans entités, sans réseau, DOCTYPE refusé, 20 Mo au plus), version lue
  dans l'espace de noms, table de correspondance unique, découpage des écritures groupées.
- Clé de dédoublonnage versionnée (`v1|`) avec rang d'occurrence et référence de détail.
- Service d'import : boîte d'entrée (xml et zip), lots triés par compte et date, une
  transaction par relevé, rapprochement interne et registre, anomalies en liste fermée,
  rejeu des relevés en attente, archivage chiffré par age, virements entre comptes propres.
- `hub finance import-history` : continuité vérifiée avant d'écrire, ouverture explicite,
  boîte d'entrée en pause pendant la reprise.
- API de lecture : comptes, écritures paginées, détail, résumé, budget, tendance, à
  catégoriser, recherche FTS5 trigram, catégories, fraîcheur, dépôt et suivi d'un import.
- CLI comptes et catégories (écriture directe en attendant le Double Sas).
- Contrat de domaine : `verify()` (contrôle profond) à côté de `health()`.

### Lot 0 — Socle

- Dépôt et outillage : uv (lockfile), ruff, mypy strict, pytest avec couverture, Hypothesis,
  import-linter, pre-commit, `scripts/check_no_data.sh`, gitleaks, image `linux/arm64`.
- Intégration continue : barrières de la section 11 et construction des images arm64.
- Fondations du cœur : réglages TOML + variables d'environnement, `Money` et devises,
  `normalize()`, masque d'IBAN, ULID et URN, acteurs, journaux JSON filtrés, erreurs
  `problem+json`, secrets chiffrés age déchiffrés en mémoire.
- Contrat de domaine (manifeste, `ProposalKind`, handlers locaux et externes) et registre par
  point d'entrée `hub.domains`.
- Base `core.db` (migration `0001_core_init`) : jetons, passkeys, sessions, codes d'amorçage,
  propositions (9 statuts, `params_hash`, `create_key`, `bundle_id`, `signature_json`),
  audit et liens en ajout seul, politiques d'approbation, défis WebAuthn, limites de débit.
- API : `/api/health`, jetons à portée par domaine, propositions à création idempotente,
  recherche, résolution d'URN, liens, schéma OpenAPI figé par un instantané.
- Passkeys : inscription par code d'amorçage, seconde passkey depuis une session, connexion,
  session de 12 h (`HttpOnly`, `Secure`, `SameSite=Strict`).
- Conteneurs sur le Mac : compose unique (Mac puis Pi), Caddy, Tailscale serve, Litestream,
  planificateur, `deploy.sh` avec retour arrière automatique, test de restauration.
- Coquille PWA : connexion passkey, page d'état, CSP stricte sans script en ligne.
- Kit de secours : modèle à imprimer.
