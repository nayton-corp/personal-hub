# Politique de calcul du patrimoine

Les règles que le hub applique pour chaque chiffre du patrimoine. Elles valent partout : écran
Patrimoine, performance, « depuis l'achat », accueil, `hub verify`. Une règle qui change ici
change dans le code de la même PR.

La règle de fond (décision du 2 novembre 2026) : **aucun solde ne vient de nulle part**. Chaque
part détenue est expliquée par une opération connue ; ce qui ne l'est pas est une *rupture*,
chiffrée, montrée tout de suite avec l'action qui la règle, et tenue à part du gain tant qu'elle
reste ouverte.

## Valeur

- **Un seul calcul.** La série du patrimoine (`patrimoine/model/engine.py`, pure et gelée) donne,
  chaque jour depuis la première écriture, la valeur et le flux de chaque ligne (instrument d'un
  compte à positions, solde d'un compte, dette) et les versements cumulés par compte. La valeur à
  une date, la performance, le résultat des cryptos et le rapprochement la lisent, ou lisent les
  mêmes parts et les mêmes cours (`model/positions.py`) : un chiffre n'a qu'une formule.
- **Les versements sont convertis au change de leur jour**, pas de celui de la valorisation :
  l'effet de change sur un compte en devise est un effet marché, comme la variation d'un cours.
  Un versement d'un jour sans change attend le premier jour qui en a, comme la ligne elle-même.
- **Un virement entre mes comptes n'est pas un versement.** Les deux côtés d'une paire
  appariée (`transfer_links`) sont exclus des versements cumulés, quelle que soit leur catégorie :
  seul l'argent qui entre ou sort du patrimoine compte, et chaque franc une fois.
- **Une position vaut ses parts fois le dernier cours connu**, converti en francs au change du
  jour. Le relevé d'un compte (rapport VIAC, solde lu par l'API) donne les parts ; sa valeur
  annoncée ne sert que si elle est positive : un relevé à 0 pour des parts tenues (SwissBorg,
  un jour sans échange) n'est pas une valeur.
- **Un cours a un âge.** Au-delà de 3 jours pour une crypto, 14 jours pour un titre ou un fonds,
  la position est signalée « cours ancien » ; sans aucun cours, « sans cours » : la valeur est
  inconnue, jamais 0 en silence.
- **Le change** est celui du jour (BCE, puis le dernier connu). Un change de plus de 7 jours
  convertit encore, mais se signale « change ancien », comme un cours ; un montant sans change
  (dividende, frais, paiement d'une dette en devise) ne vaut pas 0 : la série se dit partielle.

## Prix de revient et gain

Le gain d'un placement se lit depuis l'achat : valeur d'aujourd'hui, moins ce qu'il a coûté,
plus ce que les ventes ont réalisé. La performance « Max » de l'écran est ce même chiffre.

| Cas | Règle |
|---|---|
| Achat | Ajoute ce qu'il a coûté, frais compris. |
| Vente | Retire sa part du prix de revient au coût moyen ; la différence est réalisée. |
| Échange crypto contre crypto | Une vente suivie d'un achat, à la même valeur. |
| Transfert entre deux de mes comptes | Les parts changent de compte, le coût les suit : ni gain ni perte. |
| Récompense (staking, Earn, airdrop) | Revenu à la valeur du jour de réception, puis coût zéro. Comme l'AFC. |
| Écart de parts d'un fonds entre deux relevés | Moins d'un centième de part, sur des parts fractionnées : l'arrondi du relevé (VIAC publie deux décimales), pas une rupture. |
| Virement entre deux de mes comptes sans txid commun | Un envoi et une arrivée de la même crypto, à quelques jours, l'arrivée recevant au plus 5 % de moins (frais de retrait) : le hub te propose de les relier (carte `link_crypto_moves`). Validé, le coût suit les parts et la différence est un frais ; en attente, l'envoi est sorti au coût et l'arrivée entrée au cours du jour, chacun avec sa rupture. Rien n'est deviné à la lecture. |
| Mise en staking et sortie (parts brûlées, ETH réclamé) | Les cryptos restent à moi : le coût ne bouge pas, ni envoi ni arrivée hors de mes comptes. Une sortie lue sans marque (avant la marque `stake`) suivie d'un claim dans les 60 jours, qui rend entre 100 % et 125 % de la mise, t'est proposée en carte ; validée, elle est reliée au claim. Ce que le claim rend en plus est du gain à coût zéro. |
| Frais payés en crypto | Des parts en moins, le coût reste sur les autres : une perte. |
| Arrivée d'un portefeuille non suivi | Coûte sa valeur du jour, et ouvre une rupture « arrivée de l'extérieur » tant que tu ne l'as pas classée. |
| Envoi vers un portefeuille non suivi | Sort au coût, sans gain ni perte, et ouvre une rupture « envoi vers l'extérieur » tant que tu ne l'as pas classé. |
| Parts sans historique d'achat | Rupture « sans historique » : valeur montrée à part, hors du gain, jusqu'à l'import ou la saisie du coût. |
| Coût saisi pour une rupture | Remplace la valeur du jour comme prix de revient de ces parts. |
| 3e pilier (VIAC) | Gain = valeur moins versements nets. |

- **Coût moyen pondéré**, commun à toutes les plateformes pour une même crypto (méthode admise
  en Suisse ; la fortune privée ne paie pas d'impôt sur le gain en capital).
- **En francs et en dollars.** Chaque montant est converti au change de son jour ; l'écart entre
  le résultat en dollars converti aujourd'hui et le résultat en francs est l'effet du change.

## Performance par période

La performance d'une période (1 mois, cette année…) part de la valeur au début de la période.
Les flux sont les mêmes que ci-dessus : un achat entre à son coût, une récompense n'est pas un
apport, un envoi vers l'extérieur sort à son coût. Le rendement pondéré dans le temps (TWR) et
le rendement personnel (TRI) suivent les définitions GIPS.

## Rapprochement et ruptures

Chaque jour, par compte et par actif, le hub compare les parts relevées à la somme des
opérations connues jusqu'au relevé (et, pour un titre, la suite des relevés aux opérations
entre eux).

- **Tolérance : 1 CHF** par compte et par actif. Au-delà, l'écart est une rupture.
- Une rupture porte : le compte, l'actif, les parts, la valeur et la cause probable. L'app les
  montre sous le grand chiffre du patrimoine (« N soldes non expliqués ») et sur l'accueil ; la
  liste mène aux connexions, où l'on importe l'historique manquant.
- Un écart qu'aucun import ne comblera se règle d'un geste, depuis la liste : « J'ai payé X »
  (le prix d'achat saisi), « Garder tel quel » (le prix d'achat devient la valeur du jour où le
  hub a vu ces parts) ou, pour un envoi, « Parti hors de mes comptes » (sortie au coût). La
  décision est une proposition (`decide_break`, un Face ID, annulable : son retrait rouvre
  l'écart) ; gardée, elle sort l'écart de la liste ; une nouvelle opération du même genre le
  rouvre. Une décision couvre les parts qu'elle a vues : si les parts changent (« sans cours »
  sur 1 BONK, puis 3), ou qu'un cours ou un change plus récent est encore ancien, la rupture
  se rouvre ; rien ne vaut 0 à vie en silence.

## Collecteurs

Un passage de collecteur qui saute un réseau faute de clé, lit un historique effacé, ne trouve
pas de cours ou n'a pas pu lire une partie de la source n'est pas « ok » : il est « incomplet »,
montré sur l'accueil avec ce qu'il faut faire. Un historique plus long que les pages lues
(adresse BTC, réseau EVM, Solana) se dit `truncated` et sera relu en entier au passage suivant,
jamais tenu pour complet.

## Budget

Les totaux par catégorie (`summary`, `budget`, `flows`, `trend`) sont dans la devise de base.
Une écriture dans une autre devise (carte en euros) compte au change du jour de l'écriture ; sans
change ce jour-là, elle est laissée de côté et signalée (`missing_fx`), jamais comptée pour 0.

Une cible est gardée telle que saisie, avec sa cadence (`amount_minor`, `cadence`) : une cible
annuelle de 1'000 reste 1'000 par an, et vaut 83 par mois en lecture seulement. Les anciennes
lignes (`monthly_minor`) se relisent avec le réglage de cadence de la catégorie.

Le rythme, l'état et la projection d'une période se calculent une fois, côté serveur
(`classement/model/pace.py`), pour l'app comme pour les sentinelles : une projection dès le
7e jour (fixes au plus haut de payé et cible, variables au rythme), « au-dessus du rythme » à
plus de 10 % au-delà de la cible. Le front met en mots, il ne calcule pas.

## Contrôles

`hub verify` contrôle aussi les chiffres : le gain depuis l'achat et la performance « Max »
des cryptos s'accordent à la tolérance près (hors ruptures ouvertes) ; les ruptures ouvertes
sont comptées et chiffrées. Une fois par an, la valeur au 31 décembre se compare à la liste
des cours de l'AFC (déclaration d'impôt).

## État de départ (2 novembre 2026, agrégats)

Mesuré avant cette politique, pour juger chaque correctif.

| Mesure | Valeur |
|---|---|
| Écart performance « Max » crypto contre gain depuis l'achat | 3 031 CHF |
| … dont relevés SwissBorg USDC à 0 | 2 357 CHF |
| … dont parts sans historique | 508 CHF |
| … dont envois vers l'extérieur au cours du jour | −487 CHF |
| … dont cours USDT manquant avant le premier cours | 150 CHF |
| … dont récompenses comptées comme apport | 129 CHF |
| … dont change | 40 CHF |
| … reste | 334 CHF |
| Valeur crypto sans prix de revient | 1 748 CHF |
| Ventes sans historique d'achat | 1 280 CHF |
| Cryptos Binance sans cours | 4 (1MBABYDOGE, BONK, CGPT, ETHW) |
| Clé Etherscan | absente : Base, Arbitrum, Polygon et BSC non lus |
