<!-- Généré par `make reference` (scripts/reference.py) : ne pas modifier à la main. -->

# Connecteurs

Le catalogue des sources que le hub sait collecter (point d'entrée `hub.connectors`). Les secrets sont nommés, jamais montrés ; une connexion les donne à sa création.

| Connecteur | Nom | Domaine | Méthode | Pays | Comptes | Secrets | Réglages | Horaire |
|---|---|---|---|---|---|---|---|---|
| `bcf` | BCF | finance | browser | CH | `cash` | `contract`, `password` | — | `30 7 * * 1-5` |
| `binance` | Binance | finance | api | — | `crypto` | `api_key`, `api_secret` | — | `20 6-22/4 * * *` |
| `coinbase` | Coinbase | finance | api | — | `crypto` | `key_name`, `private_key` | — | `24 6-22/4 * * *` |
| `enable_banking` | Banque européenne (Enable Banking) | finance | open_banking | — | `cash` | `application_id`, `private_key` | `aspsp_name`, `aspsp_country`, `psu_type`, `consent_days`, `max_syncs_per_day` | `15 7,13,19 * * *` |
| `ibkr` | IBKR | finance | api | — | `securities` | `flex_token`, `query_id` | — | `45 6 * * 2-6` |
| `kucoin` | KuCoin | finance | api | — | `crypto` | `api_key`, `api_secret`, `passphrase` | — | `22 6-22/4 * * *` |
| `market` | Cours et cryptos | finance | public | — | `crypto` | — | `currencies`, `crypto`, `quotes`, `wallets` | `15 6-22/4 * * *` |
| `viac` | VIAC | finance | browser | CH | `pension` | `email`, `password` | — | `0 9 * * 0` |
