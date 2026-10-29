"""Historique Binance : chaque opération du compte, pour le Journal, et les cours des jours où
elles ont eu lieu.

Ce que l'API officielle (clé « Enable Reading ») rend, flux par flux :

- dépôts et retraits crypto (`capital/deposit/hisrec`, `capital/withdraw/history`, fenêtres de
  90 jours) avec le txId sur la chaîne et l'adresse, qui relient un retrait à son arrivée sur un
  autre portefeuille ;
- dépôts et retraits en monnaie (`fiat/orders`), achats et ventes par carte (`fiat/payments`) ;
- ordres exécutés (`myTrades`, paire par paire, les exécutions d'un ordre regroupées) ;
- conversions (`convert/tradeFlow`, fenêtres de 30 jours) ;
- récompenses Simple Earn (flexible et bloqué), groupées par actif et par jour terminé ;
- distributions (`asset/assetDividend` : airdrops, staking, Launchpool) et petits soldes
  convertis en BNB (`asset/dribblet`).

Au premier passage, tout depuis le premier dépôt ; ensuite, quelques jours de recouvrement (le
registre écarte les doublons). Un flux en échec fait reprendre le tout au passage suivant, et
le premier passage ne dépose aucune opération tant qu'il n'est pas complet : le compte s'ouvre
la veille de sa première opération, une opération plus ancienne arrivée après n'y entrerait
pas. Les transferts entre portefeuilles d'un même compte Binance (Spot, Funding, Earn) ne sont
pas des opérations : le compte `crypto:binance` les réunit déjà.

Hors API : P2P, Binance Pay, contrats à terme et marge. Une paire jamais détenue des deux
côtés (un actif acheté puis revendu en entier, jamais déposé) n'est pas lue : la lister dans
le champ `assets` des secrets.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from hub.collectors.base import Failure
from hub.collectors.http import Http
from hub.collectors.market.flow import binance_prices, fx_rates
from hub.collectors.runtime import Env

DAY_MS = 86_400_000
OVERLAP_DAYS = 3
FIAT = frozenset({"CHF", "EUR", "USD", "GBP", "TRY", "BRL", "AUD", "PLN", "RON", "UAH", "ZAR"})
STABLE = frozenset({"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"})
DEPOSIT_DONE = frozenset({1, 6})  # crédité (6 : crédité, pas encore retirable)
WITHDRAW_DONE = 6
MAX_PAGES = 50
EARN_DAYS = 29  # rewardsRecord : 30 jours au plus par appel (sinon -6021)


def _pause(ms: int) -> None:
    time.sleep(ms / 1000)


sleep: Callable[[int], None] = _pause  # en millisecondes ; remplacé dans les tests


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1000


def _day(ms: Any) -> str:
    return datetime.fromtimestamp(int(ms) // 1000, UTC).date().isoformat()


def _qty(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise Failure("invalid_file", "binance.history") from None
    if not d.is_finite():
        raise Failure("invalid_file", "binance.history")
    return d


def _text(d: Decimal) -> str:
    out = format(d.normalize(), "f")
    return "0" if out in ("-0", "") else out


@dataclass
class Op:
    id: str
    kind: str
    on_date: str
    legs: list[tuple[str, Decimal, str]] = field(default_factory=list)  # actif, quantité, rôle
    txid: str = ""
    address: str = ""
    network: str = ""
    # contre-valeur donnée par la plateforme (Coinbase : `native_amount`), par jambe
    values: dict[int, tuple[Decimal, str]] = field(default_factory=dict)

    def leg(
        self, asset: Any, quantity: Decimal, role: str, value: tuple[Decimal, str] | None = None
    ) -> Op:
        if quantity:
            if value is not None:
                self.values[len(self.legs)] = value
            self.legs.append((str(asset).upper(), quantity, role))
        return self

    def doc(self, account: str) -> dict[str, Any]:
        legs = []
        for i, (a, q, r) in enumerate(self.legs):
            leg: dict[str, str] = {"instrument": a, "quantity": _text(q), "role": r}
            if i in self.values:
                leg["value"], leg["value_currency"] = _text(self.values[i][0]), self.values[i][1]
            legs.append(leg)
        out: dict[str, Any] = {
            "account": account,
            "id": self.id,
            "kind": self.kind,
            "on_date": self.on_date,
            "legs": legs,
        }
        for k in ("txid", "address", "network"):
            if getattr(self, k):
                out[k] = getattr(self, k)[:128]
        return out


class Api:
    """Appels signés de l'historique : pause entre deux appels, une reprise après un 429, et
    les fenêtres refusées (400 : trop anciennes pour ce flux) comptées plutôt que fatales."""

    def __init__(self, env: Env, http: Http, call: Callable[..., Any]) -> None:
        self.env = env
        self.http = http
        self.call = call
        self.skipped: dict[str, int] = defaultdict(int)

    def get(self, path: str, step: str, params: dict[str, Any], pause: int = 0) -> Any:
        pause = pause or self.env.cfg.exchanges.history_pause_ms
        for attempt in (0, 1):
            if pause:
                sleep(pause)
            try:
                return self.call(self.env, self.http, path, step, params)
            except Failure as f:
                if f.detail.endswith(":http_429") and not attempt:
                    sleep(60_000)
                    continue
                if f.detail.endswith(":http_400"):
                    self.skipped[step] += 1
                    return None
                raise
        return None  # pragma: no cover - la boucle rend toujours

    def windows(
        self,
        path: str,
        step: str,
        start: int,
        end: int,
        span_days: int,
        rows_of: Callable[[Any], list[Any] | None],
        *,
        limit: int,
        params: dict[str, Any] | None = None,
        pause: int = 0,
        keys: tuple[str, str] = ("startTime", "endTime"),
    ) -> Iterator[Any]:
        """Lignes de toutes les fenêtres [start, end] ; une fenêtre pleine est coupée en deux."""
        cursor = start
        while cursor < end:
            stop = min(cursor + span_days * DAY_MS, end)
            yield from self._window(path, step, cursor, stop, rows_of, limit, params, pause, keys)
            cursor = stop + 1

    def _window(
        self,
        path: str,
        step: str,
        start: int,
        end: int,
        rows_of: Callable[[Any], list[Any] | None],
        limit: int,
        params: dict[str, Any] | None,
        pause: int,
        keys: tuple[str, str],
    ) -> Iterator[Any]:
        doc = self.get(path, step, {**(params or {}), keys[0]: start, keys[1]: end}, pause)
        if doc is None:
            return
        rows = rows_of(doc)
        if rows is None:
            raise Failure("invalid_file", step)
        if len(rows) >= limit and end - start > 60_000:
            middle = (start + end) // 2
            args = (rows_of, limit, params, pause, keys)
            yield from self._window(path, step, start, middle, *args)
            yield from self._window(path, step, middle + 1, end, *args)
            return
        yield from rows


def _list(doc: Any) -> list[Any] | None:
    return doc if isinstance(doc, list) else None


def _rows(doc: Any) -> list[Any] | None:
    rows = doc.get("rows") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else ([] if isinstance(doc, dict) else None)


def _data(doc: Any) -> list[Any] | None:
    rows = doc.get("data") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else ([] if isinstance(doc, dict) else None)


# --- flux ------------------------------------------------------------------------------------


def deposits(api: Api, start: int, end: int) -> list[Op]:
    out = []
    path, step = "/sapi/v1/capital/deposit/hisrec", "binance.deposits"
    for r in api.windows(path, step, start, end, 89, _list, limit=1000, params={"limit": 1000}):
        if int(r.get("status", -1)) not in DEPOSIT_DONE:
            continue
        op = Op(f"deposit:{r['id']}", "deposit", _day(r["insertTime"]))
        op.leg(r["coin"], _qty(r["amount"]), "deposit")
        op.txid, op.address, op.network = (
            str(r.get(k) or "") for k in ("txId", "address", "network")
        )
        out.append(op)
    return out


def withdrawals(api: Api, start: int, end: int) -> list[Op]:
    out = []
    path, step = "/sapi/v1/capital/withdraw/history", "binance.withdrawals"
    pause = api.env.cfg.exchanges.withdraw_pause_ms
    rows = api.windows(
        path, step, start, end, 89, _list, limit=1000, params={"limit": 1000}, pause=pause
    )
    for r in rows:
        if int(r.get("status", -1)) != WITHDRAW_DONE:
            continue
        on = str(r.get("completeTime") or r["applyTime"])[:10]
        op = Op(f"withdraw:{r['id']}", "withdrawal", date.fromisoformat(on).isoformat())
        # `amount` arrive sur l'autre portefeuille, les frais de réseau s'y ajoutent
        op.leg(r["coin"], -_qty(r["amount"]), "withdrawal")
        op.leg(r["coin"], -_qty(r.get("transactionFee") or 0), "fee")
        op.txid, op.address, op.network = (
            str(r.get(k) or "") for k in ("txId", "address", "network")
        )
        out.append(op)
    return out


def _paged(api: Api, path: str, step: str, params: dict[str, Any]) -> Iterator[Any]:
    """`fiat/orders` et `fiat/payments` : pages de 500, toute la période d'un coup."""
    for page in range(1, MAX_PAGES + 1):
        doc = api.get(path, step, {**params, "page": page, "rows": 500})
        if doc is None:
            return
        rows = _data(doc)
        if rows is None:
            raise Failure("invalid_file", step)
        yield from rows
        if len(rows) < 500:
            return


def fiat(api: Api, start: int, end: int) -> list[Op]:
    """Virements en monnaie (SEPA, carte) et achats ou ventes par carte."""
    out = []
    span = {"beginTime": start, "endTime": end}
    for t, kind in ((0, "fiat_deposit"), (1, "fiat_withdrawal")):
        for r in _paged(
            api, "/sapi/v1/fiat/orders", "binance.fiat", {**span, "transactionType": t}
        ):
            if r.get("status") not in ("Successful", "Completed"):
                continue
            ccy, fee = r["fiatCurrency"], _qty(r.get("totalFee") or 0)
            op = Op(f"fiat:{r['orderNo']}", kind, _day(r["createTime"]))
            if t == 0:  # le montant demandé quitte la banque, les frais sont pris dessus
                op.leg(ccy, _qty(r["indicatedAmount"]), "deposit")
            else:  # `amount` arrive à la banque
                op.leg(ccy, -_qty(r["amount"]), "withdrawal")
            out.append(op.leg(ccy, -fee, "fee"))
    for t, kind in ((0, "card_buy"), (1, "card_sell")):
        path = "/sapi/v1/fiat/payments"
        for r in _paged(api, path, "binance.payments", {**span, "transactionType": t}):
            if r.get("status") != "Completed":
                continue
            ccy, coin = r["fiatCurrency"], r["cryptoCurrency"]
            fee, source, got = (
                _qty(r.get(k) or 0) for k in ("totalFee", "sourceAmount", "obtainAmount")
            )
            op = Op(f"payment:{r['orderNo']}", kind, _day(r["createTime"]))
            if t == 0:  # la carte paie `sourceAmount`, frais compris
                op.leg(ccy, source, "deposit").leg(ccy, -(source - fee), "trade")
                op.leg(ccy, -fee, "fee").leg(coin, got, "trade")
            else:
                op.leg(coin, -source, "trade").leg(ccy, got + fee, "trade")
                op.leg(ccy, -fee, "fee").leg(ccy, -got, "withdrawal")
            out.append(op)
    return out


def converts(api: Api, start: int, end: int) -> list[Op]:
    out = []
    path, step = "/sapi/v1/convert/tradeFlow", "binance.convert"
    for r in api.windows(
        path, step, start, end, 29, _list_of("list"), limit=1000, params={"limit": 1000}
    ):
        if r.get("orderStatus") != "SUCCESS":
            continue
        op = Op(f"convert:{r['orderId']}", "convert", _day(r["createTime"]))
        op.leg(r["fromAsset"], -_qty(r["fromAmount"]), "trade")
        out.append(op.leg(r["toAsset"], _qty(r["toAmount"]), "trade"))
    return out


def _list_of(key: str) -> Callable[[Any], list[Any] | None]:
    def rows(doc: Any) -> list[Any] | None:
        if not isinstance(doc, dict):
            return None
        value = doc.get(key)
        return value if isinstance(value, list) else []

    return rows


def rewards(api: Api, start: int, end: int, today: date) -> list[Op]:
    """Récompenses Simple Earn, une opération par actif et par jour terminé (les récompenses
    en temps réel tombent chaque minute)."""
    by_day: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    streams = [("flexible", t, "rewards") for t in ("BONUS", "REALTIME", "REWARDS")]
    streams.append(("locked", "", "amount"))
    for product, kind, amount_key in streams:
        path = f"/sapi/v1/simple-earn/{product}/history/rewardsRecord"
        params: dict[str, Any] = {"size": 100}
        if kind:
            params["type"] = kind
        step = f"binance.rewards_{product}"
        for r in _earn_pages(api, path, step, start, end, params):
            day = _day(r["time"])
            if day < today.isoformat():
                by_day[(str(r["asset"]).upper(), day, product)] += _qty(r[amount_key])
    return [
        Op(f"reward:{product}:{asset}:{day}", "reward", day).leg(asset, q, "income")
        for (asset, day, product), q in sorted(by_day.items())
        if q
    ]


def _earn_pages(
    api: Api, path: str, step: str, start: int, end: int, params: dict[str, Any]
) -> Iterator[Any]:
    cursor = start
    while cursor < end:
        stop = min(cursor + EARN_DAYS * DAY_MS, end)
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            doc = api.get(
                path, step, {**params, "startTime": cursor, "endTime": stop, "current": page}
            )
            rows = _rows(doc) if doc is not None else []
            if rows is None:
                raise Failure("invalid_file", step)
            yield from rows
            seen += len(rows)
            if not rows or seen >= int(doc.get("total") or 0):
                break
        else:
            api.skipped[f"{step}:truncated"] += 1
        cursor = stop + 1


# les intérêts Simple Earn viennent de `rewards` : pas deux fois
_EARN_INFO = ("simple earn", "flexible", "locked")


def dividends(api: Api, start: int, end: int) -> list[Op]:
    out = []
    path, step = "/sapi/v1/asset/assetDividend", "binance.dividends"
    for r in api.windows(path, step, start, end, 89, _rows, limit=500, params={"limit": 500}):
        info = str(r.get("enInfo") or "")
        if any(k in info.lower() for k in _EARN_INFO):
            continue
        op = Op(f"dividend:{r.get('tranId') or r['id']}", "distribution", _day(r["divTime"]))
        out.append(op.leg(r["asset"], _qty(r["amount"]), "income"))
    return out


def dust(api: Api, start: int) -> list[Op]:
    """Petits soldes convertis en BNB (les 100 dernières conversions, que l'API garde)."""
    doc = api.get("/sapi/v1/asset/dribblet", "binance.dust", {})
    if doc is None:
        return []
    groups = doc.get("userAssetDribblets") if isinstance(doc, dict) else None
    if not isinstance(groups, list):
        raise Failure("invalid_file", "binance.dust")
    out = []
    for g in groups:
        if int(g["operateTime"]) < start:
            continue
        op = Op(f"dust:{g['transId']}", "dust", _day(g["operateTime"]))
        for d in g.get("userAssetDribbletDetails") or []:
            fee = _qty(d.get("serviceChargeAmount") or 0)
            op.leg(d["fromAsset"], -_qty(d["amount"]), "trade")
            op.leg("BNB", _qty(d["transferedAmount"]) + fee, "trade").leg("BNB", -fee, "fee")
        out.append(op)
    return out


def trades(api: Api, assets: set[str], memory: dict[str, int]) -> tuple[list[Op], dict[str, int]]:
    """Ordres exécutés des paires dont les deux actifs sont connus du compte ; les exécutions
    d'un même ordre (dans un même passage) sont une seule opération. `memory` : prochain
    identifiant d'exécution à lire, par paire."""
    url = f"{api.env.cfg.exchanges.binance_url}/api/v3/exchangeInfo"
    info = api.http.json(url, "binance.symbols")
    symbols = info.get("symbols") if isinstance(info, dict) else None
    if not isinstance(symbols, list):
        raise Failure("invalid_file", "binance.symbols")
    pairs = {
        str(s["symbol"]): (str(s["baseAsset"]), str(s["quoteAsset"]))
        for s in symbols
        if isinstance(s, dict) and s.get("baseAsset") in assets and s.get("quoteAsset") in assets
    }
    out, cursor = [], dict(memory)
    for symbol, (base, quote) in sorted(pairs.items()):
        fills: list[dict[str, Any]] = []
        for _page in range(MAX_PAGES):
            params = {"symbol": symbol, "fromId": cursor.get(symbol, 0), "limit": 1000}
            rows = api.get("/api/v3/myTrades", "binance.trades", params)
            if rows is None:
                break
            if not isinstance(rows, list):
                raise Failure("invalid_file", "binance.trades")
            fills += rows
            if rows:
                cursor[symbol] = max(int(r["id"]) for r in rows) + 1
            if len(rows) < 1000:
                break
        by_order: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for f in fills:
            by_order[f["orderId"]].append(f)
        for order, group in sorted(by_order.items(), key=lambda x: min(int(f["id"]) for f in x[1])):
            first = min(group, key=lambda f: int(f["id"]))
            op = Op(f"trade:{symbol}:{order}:{first['id']}", "trade", _day(first["time"]))
            sign = 1 if first.get("isBuyer") else -1
            op.leg(base, sign * sum((_qty(f["qty"]) for f in group), Decimal(0)), "trade")
            op.leg(quote, -sign * sum((_qty(f["quoteQty"]) for f in group), Decimal(0)), "trade")
            fees: dict[str, Decimal] = defaultdict(Decimal)
            for f in group:
                fees[str(f["commissionAsset"]).upper()] += _qty(f["commission"])
            for asset, fee in sorted(fees.items()):
                op.leg(asset, -fee, "fee")
            out.append(op)
    return out, cursor


# --- passage ---------------------------------------------------------------------------------


@dataclass
class History:
    operations: list[dict[str, Any]]
    prices: list[dict[str, str]]
    fx: list[dict[str, str]]
    failed: list[str]
    commit: Callable[[], None]


def _price_rows(env: Env, http: Http, ops: list[Op], failed: list[str]) -> list[dict[str, str]]:
    """Clôtures Binance (paire USDT) des actifs aux jours de leurs opérations : de quoi les
    valoriser hors des cours CoinGecko (un an, quelques cryptos)."""
    needed: dict[str, set[str]] = defaultdict(set)
    for op in ops:
        for asset, _q, _r in op.legs:
            if asset not in FIAT and asset not in STABLE:
                needed[asset].add(op.on_date)
    out = []
    for asset, days in sorted(needed.items()):
        start, end = (
            date.fromisoformat(min(days)),
            date.fromisoformat(max(days)) + timedelta(days=1),
        )
        try:
            rows = binance_prices(env, http, [asset], start, end)
        except Failure as f:
            if not f.detail.endswith(":http_400"):  # 400 : pas de paire USDT
                failed.append(f"prices.{asset.lower()}:{f.outcome}")
            continue
        out += [r for r in rows if r["on_date"] in days]
    return out


def collect(
    env: Env, http: Http, call: Callable[..., Any], account: str, held: set[str]
) -> History:
    api = Api(env, http, call)
    memory = env.memory
    since = memory.get("history_since")
    full = since is None
    first = date.fromisoformat(str(env.creds.get("since") or env.cfg.exchanges.binance_since))
    start_day = first if full else date.fromisoformat(since) - timedelta(days=OVERLAP_DAYS)
    start, end = _ms(start_day), _ms(env.today + timedelta(days=1)) - 1
    failed: list[str] = []
    ops: list[Op] = []

    def stream(name: str, fn: Callable[[], list[Op]]) -> None:
        try:
            ops.extend(fn())
        except Failure as f:
            if f.outcome == "auth_error":
                raise
            failed.append(f"{name}:{f.outcome}")
        except (KeyError, TypeError, ValueError):
            failed.append(f"{name}:invalid_file")

    stream("deposits", lambda: deposits(api, start, end))
    stream("fiat", lambda: fiat(api, start, end))
    if full and ops:  # rien ne sort ni ne s'échange avant le premier apport
        start = _ms(date.fromisoformat(min(op.on_date for op in ops)))
    stream("withdrawals", lambda: withdrawals(api, start, end))
    stream("convert", lambda: converts(api, start, end))
    # récompenses : relues depuis le début tant qu'un passage ne les a pas toutes lues
    # (fenêtres trop larges jusqu'à la v0.9.9)
    earn_full = memory.get("rewards_since") is None
    first_day = memory.get("first_day")
    earn_start = start
    if earn_full and not full:
        earn_start = _ms(date.fromisoformat(first_day) if first_day else first)
    stream("rewards", lambda: rewards(api, earn_start, end, env.today))
    stream("dividends", lambda: dividends(api, start, end))
    stream("dust", lambda: dust(api, start))
    extra = env.creds.get("assets") or []
    assets = (
        held
        | {a for op in ops for a, _q, _r in op.legs}
        | set(memory.get("assets", []))
        | {str(a).upper() for a in (extra if isinstance(extra, list) else [])}
    )
    cursor: dict[str, int] = dict(memory.get("trade_ids", {}))
    try:
        found, cursor = trades(api, assets, cursor)
        ops += found
    except Failure as f:
        if f.outcome == "auth_error":
            raise
        failed.append(f"trades:{f.outcome}")
    except (KeyError, TypeError, ValueError):
        failed.append("trades:invalid_file")
    failed += [
        f"{step.removeprefix('binance.')}:skipped={n}" for step, n in sorted(api.skipped.items())
    ]
    prices = _price_rows(env, http, ops, failed) if ops else []
    fx: list[dict[str, str]] = []
    if (
        full and ops
    ):  # le change BCE depuis la première opération (le collecteur « market » : un an)
        try:
            fx = fx_rates(
                env, http, date.fromisoformat(min(op.on_date for op in ops)), until=env.today
            )
        except Failure as f:
            failed.append(f"fx:{f.outcome}")
    broken = [f for f in failed if "skipped=" not in f]
    if full and broken:
        # premier passage incomplet : rien au registre, tout est relu la prochaine fois
        ops, prices, fx = [], [], []
    ops.sort(key=lambda op: (op.on_date, op.id))

    earn_ok = not [f for f in failed if f.startswith("rewards")]

    def commit() -> None:
        memory.put("assets", sorted(assets))
        if full and ops:
            memory.put("first_day", ops[0].on_date)
        if earn_ok and not (full and broken):
            memory.put("rewards_since", env.today.isoformat())
        if not (full and broken):
            memory.put("trade_ids", cursor)
        if not broken:
            memory.put("history_since", env.today.isoformat())

    return History([op.doc(account) for op in ops], prices, fx, failed, commit)
