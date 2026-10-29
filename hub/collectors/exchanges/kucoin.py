"""Collecteur KuCoin : tous les comptes (main, trade, marge…) et les placements Earn, par l'API
officielle (signature HMAC-SHA256, clé v2). Clé avec la permission « General » seulement.

L'historique vient du grand livre du compte (`/api/v1/accounts/ledgers`), que KuCoin garde un
an et rend par tranches de 24 heures : dépôts, retraits, échanges (les deux côtés d'un ordre
regroupés), conversions, récompenses. Les transferts entre comptes KuCoin (principal, trading)
sont internes ; un type inconnu est compté dans le détail (`type.<nom>:skipped=n`)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.exchanges import history
from hub.collectors.exchanges.binance_history import DAY_MS, History, Op, _qty
from hub.collectors.exchanges.common import now_ms, runner
from hub.collectors.http import Http
from hub.collectors.runtime import Env

MAX_PAGES = 10
AUTH_CODES = {"400001", "400002", "400003", "400004", "400005", "400006", "400007", "411100"}


def _sign(secret: str, message: str) -> str:
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def get(env: Env, http: Http, path: str, step: str) -> Any:
    secret = env.secret("api_secret")
    stamp = str(now_ms())
    headers = {
        "KC-API-KEY": env.secret("api_key"),
        "KC-API-SIGN": _sign(secret, stamp + "GET" + path),
        "KC-API-TIMESTAMP": stamp,
        "KC-API-PASSPHRASE": _sign(secret, env.secret("passphrase")),
        "KC-API-KEY-VERSION": "2",
    }
    doc = http.json(f"{env.cfg.exchanges.kucoin_url}{path}", step, headers=headers)
    code = str(doc.get("code")) if isinstance(doc, dict) else ""
    if code in AUTH_CODES:
        raise Failure("auth_error", f"{step}:{code}")
    if code != "200000":
        raise Failure("site_unavailable", f"{step}:code")
    return doc.get("data")


def fetch(env: Env, http: Http) -> list[tuple[str, Any]]:
    try:
        out = [
            (a["currency"], a["balance"])
            for a in get(env, http, "/api/v1/accounts", "kucoin.accounts")
        ]
        for page in range(1, MAX_PAGES + 1):
            path = f"/api/v1/earn/hold-assets?currentPage={page}&pageSize=50"
            data = get(env, http, path, "kucoin.earn")
            out += [(a["currency"], a["holdAmount"]) for a in data["items"]]
            if page >= int(data.get("totalPage") or 1):
                break
    except (KeyError, TypeError):
        raise Failure("invalid_file", "kucoin.balances") from None
    return out


LEDGER_DAYS = 365  # ce que KuCoin garde


def _role(biz: str) -> str | None:
    """Rôle d'une ligne du grand livre selon son type ; `None` : interne, `""` : inconnu."""
    b = biz.lower()
    if "transfer" in b:
        return None
    if "deposit" in b:
        return "deposit"
    if "withdraw" in b:
        return "withdrawal"
    if any(k in b for k in ("exchange", "trade", "convert", "lite", "dust")):
        return "trade"
    if any(
        k in b
        for k in ("reward", "earn", "staking", "interest", "bonus", "airdrop", "distribution")
    ):
        return "income"
    if "fee" in b:
        return "fee"
    return ""


def _context(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        out = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def read_history(env: Env, http: Http, start: date | None) -> tuple[list[Op], list[str]]:
    oldest = env.today - timedelta(days=LEDGER_DAYS - 1)
    first = max(start, oldest) if start else oldest
    cursor = int(datetime(first.year, first.month, first.day, tzinfo=UTC).timestamp()) * 1000
    stop = (
        int(datetime.combine(env.today + timedelta(days=1), datetime.min.time(), UTC).timestamp())
        * 1000
    )
    rows: list[dict[str, Any]] = []
    while cursor < stop:
        end = min(cursor + DAY_MS - 1, stop - 1)
        for page in range(1, MAX_PAGES + 1):
            history.pause(env)
            path = (
                f"/api/v1/accounts/ledgers?startAt={cursor}&endAt={end}"
                f"&currentPage={page}&pageSize=500"
            )
            data = get(env, http, path, "kucoin.ledgers")
            rows += data["items"]
            if page >= int(data.get("totalPage") or 1):
                break
        cursor = end + 1
    skipped: dict[str, int] = defaultdict(int)
    ops: dict[str, Op] = {}
    for r in sorted(rows, key=lambda r: (int(r["createdAt"]), str(r["id"]))):
        biz = str(r.get("bizType") or "")
        role = _role(biz)
        if role is None:
            continue
        if role == "":
            skipped[biz[:30].replace(" ", "_")] += 1
            continue
        sign = 1 if r.get("direction") == "in" else -1
        context = _context(r.get("context"))
        order = context.get("orderId") or context.get("tradeId")
        key = f"order:{order}" if role == "trade" and order else f"ledger:{r['id']}"
        day = datetime.fromtimestamp(int(r["createdAt"]) // 1000, UTC).date().isoformat()
        kind = {"deposit": "deposit", "withdrawal": "withdrawal", "income": "reward"}.get(
            role, "trade"
        )
        # un ordre exécuté en plusieurs fois sur deux passages : deux opérations distinctes
        grouped = role == "trade" and order
        op = ops.setdefault(key, Op(f"{key}:{r['id']}" if grouped else key, kind, day))
        ccy = str(r["currency"]).upper()
        leg_role = "fee" if role == "fee" else role
        op.leg(ccy, sign * _qty(r["amount"]), leg_role)
        op.leg(ccy, -_qty(r.get("fee") or 0), "fee")
        op.txid = op.txid or str(context.get("txId") or context.get("walletTxId") or "")
    notes = [f"type.{t}:skipped={n}" for t, n in sorted(skipped.items())]
    return list(ops.values()), notes


def history_of(env: Env, http: Http, account: str, held: set[str]) -> History:
    return history.collect(env, http, account, read_history)


run = runner(fetch, history_of)
