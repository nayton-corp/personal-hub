"""Collecteur Coinbase : tous les portefeuilles du compte (ETH en staking compris), par l'API
Coinbase App v2 avec une clé CDP (JWT signé ES256, ou EdDSA pour une clé Ed25519). Clé avec la
permission « View » seulement.

L'historique : les transactions terminées de chaque portefeuille (achats, ventes, envois et
réceptions avec leur hash, staking), une jambe chacune, à la contre-valeur que donne Coinbase
(`native_amount`). Les mouvements entre portefeuilles Coinbase (staking, Advanced Trade) sont
internes au compte ; un type inconnu est compté dans le détail (`type.<nom>:skipped=n`)."""

from __future__ import annotations

import base64
import json
import secrets as pysecrets
import time
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from hub.collectors.base import Failure
from hub.collectors.exchanges import history
from hub.collectors.exchanges.binance_history import History, Op, _qty
from hub.collectors.exchanges.common import runner
from hub.collectors.http import Http
from hub.collectors.runtime import Env

MAX_PAGES = 50


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(key_name: str, private_key: str, uri: str, now: int | None = None) -> str:
    """Jeton de 2 minutes pour une requête (`uri` : « GET api.coinbase.com/v2/accounts »)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    now = int(time.time()) if now is None else now
    pem = private_key.replace("\\n", "\n").strip()
    try:
        if pem.startswith("-----BEGIN"):
            key: Any = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError
            alg = "ES256"
        else:  # clé Ed25519 en base64 : graine de 32 octets (suivie de la clé publique)
            key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(pem)[:32])
            alg = "EdDSA"
    except ValueError:
        raise Failure("auth_error", "secret:private_key") from None
    header = {"alg": alg, "kid": key_name, "nonce": pysecrets.token_hex(16), "typ": "JWT"}
    payload = {"sub": key_name, "iss": "cdp", "nbf": now, "exp": now + 120, "uri": uri}
    signing_input = ".".join(
        _b64url(json.dumps(x, separators=(",", ":")).encode()) for x in (header, payload)
    ).encode()
    if alg == "ES256":
        r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        signature = key.sign(signing_input)
    return signing_input.decode() + "." + _b64url(signature)


def _pages(env: Env, http: Http, path: str, step: str) -> Any:
    """Les pages d'une liste de l'API v2 (`next_uri`), une à une."""
    base = env.cfg.exchanges.coinbase_url
    host = urlsplit(base).netloc
    key_name, private_key = env.secret("key_name"), env.secret("private_key")
    next_path: str | None = path
    for _page in range(MAX_PAGES):
        if not next_path:
            return
        token = jwt(key_name, private_key, f"GET {host}{next_path.split('?', 1)[0]}")
        doc = http.json(f"{base}{next_path}", step, headers={"Authorization": f"Bearer {token}"})
        try:
            yield doc["data"]
            next_path = (doc.get("pagination") or {}).get("next_uri") or None
        except (KeyError, TypeError, AttributeError):
            raise Failure("invalid_file", step) from None


def _accounts(env: Env, http: Http) -> list[dict[str, Any]]:
    return [
        a for page in _pages(env, http, "/v2/accounts?limit=100", "coinbase.accounts") for a in page
    ]


def fetch(env: Env, http: Http) -> list[tuple[str, Any]]:
    try:
        return [(a["balance"]["currency"], a["balance"]["amount"]) for a in _accounts(env, http)]
    except (KeyError, TypeError):
        raise Failure("invalid_file", "coinbase.accounts") from None


# type de transaction v2 → rôle de la jambe ; `None` : mouvement interne au compte Coinbase
ROLES: dict[str, str | None] = {
    "send": "transfer",  # envoi (négatif) ou réception (positif) sur la chaîne
    "receive": "transfer",
    "fiat_deposit": "transfer",
    "fiat_withdrawal": "transfer",
    "buy": "trade",
    "sell": "trade",
    "trade": "trade",
    "advanced_trade_fill": "trade",
    "retail_simple_dust": "trade",
    "wrap_asset": "trade",
    "unwrap_asset": "trade",
    "staking_reward": "income",
    "inflation_reward": "income",
    "interest": "income",
    "earn_payout": "income",
    "incentives_rewards_payout": "income",
    "incentives_shared_clawback": "income",
    "pro_deposit": None,
    "pro_withdrawal": None,
    "exchange_deposit": None,
    "exchange_withdrawal": None,
    "vault_withdrawal": None,
    "staking_transfer": None,
    "unstaking_transfer": None,
    "retail_eth2_deprecation": None,  # ETH2 rendu en ETH : compté comme ETH des deux côtés
    "transfer": None,
}
KIND = {"transfer": "deposit", "trade": "trade", "income": "reward"}


def _op(env: Env, tx: dict[str, Any]) -> Op | None:
    role = ROLES.get(str(tx.get("type")))
    amount = _qty(tx["amount"]["amount"])
    if role is None or not amount:
        return None
    aliases = env.cfg.exchanges.aliases
    ccy = str(tx["amount"]["currency"]).upper()
    ccy = aliases.get(ccy, ccy)
    native = tx.get("native_amount") or {}
    value = (
        (_qty(native["amount"]), str(native["currency"]).upper()) if native.get("amount") else None
    )
    day = date.fromisoformat(str(tx["created_at"])[:10]).isoformat()
    if role == "transfer":
        role = "deposit" if amount > 0 else "withdrawal"
    kind = KIND.get(role, role)
    if tx.get("type") in ("fiat_deposit", "fiat_withdrawal"):
        kind = str(tx["type"])
    op = Op(f"tx:{tx['id']}", kind, day)
    network = tx.get("network") or {}
    fee = network.get("transaction_fee") or {}
    sent = network.get("transaction_amount") or {}
    if role == "withdrawal" and fee.get("amount") and sent.get("amount"):
        # l'envoi débite le montant envoyé et les frais de réseau
        op.leg(ccy, -_qty(sent["amount"]), "withdrawal")
        op.leg(ccy, -_qty(fee["amount"]), "fee")
    else:
        op.leg(ccy, amount, role, value)
    op.txid = str(network.get("hash") or "")
    return op


def read_history(env: Env, http: Http, start: date | None) -> tuple[list[Op], list[str]]:
    """Transactions terminées de chaque portefeuille, de la plus récente à `start`."""
    ops: list[Op] = []
    skipped: dict[str, int] = {}
    for account in _accounts(env, http):
        path = f"/v2/accounts/{account['id']}/transactions?limit=100&order=desc"
        for page in _pages(env, http, path, "coinbase.transactions"):
            history.pause(env)
            older = False
            for tx in page:
                if start is not None and str(tx.get("created_at"))[:10] < start.isoformat():
                    older = True
                    break
                if tx.get("status") != "completed":
                    continue
                if str(tx.get("type")) not in ROLES:
                    skipped[str(tx.get("type"))[:30]] = skipped.get(str(tx.get("type"))[:30], 0) + 1
                    continue
                op = _op(env, tx)
                if op is not None:
                    ops.append(op)
            if older:
                break
    notes = [f"type.{t}:skipped={n}" for t, n in sorted(skipped.items())]
    return ops, notes


def history_of(env: Env, http: Http, account: str, held: set[str]) -> History:
    return history.collect(env, http, account, read_history)


run = runner(fetch, history_of)
