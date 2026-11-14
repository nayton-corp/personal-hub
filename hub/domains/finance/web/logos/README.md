# Logos des établissements, plateformes et commerçants

Fichiers SVG carrés (fond compris), servis avec l'app sous `/d/finance/logos/` : aucun logo n'est
demandé à un service tiers à l'affichage (rien ne révèle quels comptes on a). La pastille les rogne
en rond. Un nom sans logo garde son sigle ou ses initiales (`meta.js`).

Les marques appartiennent à leurs propriétaires ; elles ne servent ici qu'à reconnaître un compte ou
un commerçant (usage nominatif), sans lien ni approbation de leur part.

| Logo | Source du tracé |
| --- | --- |
| cryptos (`coins/<symbole>.svg`, 92) ; binance, coinbase, kucoin, swissborg (plateformes) ; ledger, metamask, phantom, trustwallet, coinbasewallet (portefeuilles) ; multiversx (réseau) | [web3icons](https://github.com/0xa3k5/web3icons) `@web3icons/core` 4.0.59, MIT, variante « background » |
| tao (Bittensor) | τ blanc sur noir, dessiné ici |
| ishares, vanguard, ubs, xtrackers, invesco, fidelity, zkb (émetteurs de fonds, d'après le nom du fonds) | repris de SVG publics (selfh.st/icons, detain/svg-logos, imskr/northstar, dharunashokkumar/api.dharun.dev), la marque seule |
| sbb (CFF) | signet du design system des CFF, [`@sbb-esta/lyne-elements`](https://github.com/sbb-design-systems/lyne-components) 5.13.2, MIT |
| ibkr | [selfh.st/icons](https://github.com/selfhst/icons) `interactive-brokers.svg` |
| migros | [migros/fotoobo](https://github.com/migros/fotoobo) `docs/source/migros.svg`, en blanc sur orange |
| coop | logo Coop (Suisse) repris d'un SVG public, sur fond blanc |
| swisscom | logo Swisscom (CNCF landscape, `hosted_logos/swisscom.svg`), le symbole sans le mot |
| twint | [tabler](https://github.com/tabler/tabler) `core/img/payments/twint.svg`, le symbole sans le mot |
| bcf | emblème de la Banque Cantonale de Fribourg (traits et chevron), sans les lettres |
| viac | hexagone vert de VIAC redessiné (forme d'après Lawnicons, teinte relevée sur le logo) |

Ajouter un logo : un SVG carré `viewBox` quelconque, fond plein, marque centrée avec une marge
(un rond de la taille du carré la contient), puis son nom dans `LOGOS` et `LOGO_TINT` (`meta.js`)
et sa règle : `INST_LOGOS` / `MERCHANT_LOGOS` pour une marque internationale, `institution_logos` /
`merchant_logos` du pack pays pour une marque du pays.
