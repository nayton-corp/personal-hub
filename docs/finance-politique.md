# Politique de calcul du patrimoine

Les règles que le hub applique pour chaque chiffre du patrimoine. Elles valent partout : écran
Patrimoine, performance, « depuis l'achat », accueil, `hub verify`. Une règle qui change ici
change dans le code de la même PR.

La règle de fond (décision du 2 novembre 2026) : **aucun solde ne vient de nulle part**. Chaque
part détenue est expliquée par une opération connue ; ce qui ne l'est pas est une *rupture*,
chiffrée, montrée tout de suite avec l'action qui la règle, et tenue à part du gain tant qu'elle
reste ouverte.

## Valeur

- **Une position vaut ses parts fois le dernier cours connu**, converti en francs au change du
  jour. Le relevé d'un compte (rapport VIAC, solde lu par l'API) donne les parts ; sa valeur
  annoncée ne sert que si elle est positive : un relevé à 0 pour des parts tenues (SwissBorg,
  un jour sans échange) n'est pas une valeur.
- **Un cours a un âge.** Au-delà de 3 jours pour une crypto, 14 jours pour un titre ou un fonds,
  la position est signalée « cours ancien » ; sans aucun cours, « sans cours » : la valeur est
  inconnue, jamais 0 en silence.
- **Le change** est celui du jour (BCE, puis le dernier connu).

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
- Une décision enregistrée par l'API (`POST /finance/breaks/decide` : coût saisi, garder tel
  quel, « parti ») sort la rupture de la liste ; l'app ne propose pas encore ces gestes.

## Collecteurs

Un passage de collecteur qui saute un réseau faute de clé, lit un historique effacé, ne trouve
pas de cours ou n'a pas pu lire une partie de la source n'est pas « ok » : il est « incomplet »,
montré sur l'accueil avec ce qu'il faut faire.

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
