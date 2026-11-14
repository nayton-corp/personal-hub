# Logos des établissements, plateformes, commerçants et actifs

Servis avec l'app sous `/d/finance/logos/` : aucun logo n'est demandé à un service tiers à
l'affichage (rien ne révèle quels comptes on a). La pastille les rogne en rond. Un nom sans logo
garde son sigle ou ses initiales (`meta.js`).

Les marques appartiennent à leurs propriétaires ; elles ne servent ici qu'à reconnaître un compte,
un commerçant ou un actif (usage nominatif), sans lien ni approbation de leur part.

- `<nom>.png` (128 px) : l'icône actuelle de l'app de la marque sur l'App Store suisse
  (`itunes.apple.com/search?country=ch`, image `128x128bb.png`), relevée le 14.11.2026. TWINT :
  l'hexagone de l'app « Prepaid TWINT », sans le mot. Sans app propre (iShares, Invesco, Vanguard,
  Xtrackers, Fidelity) : leur marque, tracée en SVG puis rendue en PNG.
- `coins/<symbole>.svg` : les cryptos, [web3icons](https://github.com/0xa3k5/web3icons)
  `@web3icons/core` 4.0.59 (MIT), variante « background » ; `tao` (Bittensor) dessiné ici.

Ajouter un logo : l'icône carrée 128 px en PNG, puis son nom dans `LOGOS` (`meta.js`) et sa règle :
`INST_LOGOS` / `MERCHANT_LOGOS` / `FUND_LOGOS` pour une marque internationale, `institution_logos`
/ `merchant_logos` / `fund_logos` du pack pays pour une marque du pays. Une crypto : son SVG dans
`coins/` et son symbole dans `COINS`.
