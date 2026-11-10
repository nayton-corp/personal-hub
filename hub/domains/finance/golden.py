"""Étalon des agrégats de la finance, `hub finance golden` (refactoring, étape 0).

`save` fige ce que l'app affiche à une date : valeur du patrimoine et de chaque compte,
instantanés, positions, performance, ruptures du rapprochement, totaux du budget, dettes, et
des compteurs de tables. `check` recalcule les mêmes agrégats à la même date, avec le code du
jour, et nomme chaque écart au centime. Un étalon ne contient que des chiffres et des
identifiants : aucune écriture, aucun libellé, aucun IBAN (les mots sont retirés à la source).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

import hub
from hub.domains.finance.classement.app import totals
from hub.domains.finance.patrimoine.app import (
    account_list,
    debts,
    holdings,
    perf_lines,
    performance,
    reconcile,
    snapshots,
    valuation,
)
from hub.domains.finance.registre.model import period
from hub.domains.finance.registre.model.amounts import previous_months
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.money import base_currency

VERSION = 1
MONTHS = 13  # mois budgétaires figés, le courant compris
STEP = "month"
TABLES = (
    "accounts",
    "entries",
    "categorizations",
    "checkpoints",
    "imports",
    "trades",
    "holdings",
    "prices",
    "fx_rates",
    "compositions",
    "transfer_links",
    "snapshots",
    "reconcile_decisions",
    "debts",
    "debt_balances",
    "debt_balance_records",
    "reconcile_withdrawals",
    "budget_period_rules",
    "crypto_moves",
    "crypto_links",
    "crypto_link_withdrawals",
)
# clés retirées des agrégats : des mots (noms, libellés, références), jamais des chiffres
WORDS = frozenset(
    {
        "account",
        "category_name",
        "counterparty",
        "display",
        "external_ref",
        "iban",
        "institution",
        "label",
        "lender",
        "name",
        "names",
        "note",
        "symbol",
        "title",
    }
)
EXAMPLES = 50


class GoldenError(ValueError):
    pass


def plain(value: Any) -> Any:
    """Un montant `{minor, currency, display}` devient son entier, un Decimal du texte, et les
    mots (noms, libellés) disparaissent : il ne reste que des chiffres et des clés."""
    if isinstance(value, dict):
        if {"minor", "currency", "display"} <= value.keys():
            return int(value["minor"])
        return {str(k): plain(v) for k, v in value.items() if str(k) not in WORDS}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _counts(conn: Connection) -> dict[str, int]:
    present = {
        str(r[0]) for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
    }
    return {
        t: int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one())  # noqa: S608
        for t in TABLES
        if t in present
    }


def _valuation(conn: Connection, as_of: str) -> dict[str, Any]:
    v = valuation.value_at(conn, as_of)
    return {
        "net_worth": v.net_worth,
        "deposits": v.deposits,
        "liquid": v.liquid,
        "by_envelope": dict(v.by_envelope),
        "by_account": dict(v.by_account),
        "missing_fx": sorted(v.missing_fx),
        "missing_prices": sorted(v.missing_prices),
    }


def _snapshots(conn: Connection) -> list[dict[str, Any]]:
    return [
        {
            "on_date": r["on_date"],
            "net_worth": r["net_worth_minor"],
            "deposits_cum": r["deposits_cum_minor"],
            "by_envelope": json.loads(r["by_envelope_json"]),
            "by_account": json.loads(r["by_account_json"]),
        }
        for r in snapshots.stored(conn)
    ]


def _accounts(conn: Connection) -> dict[str, Any]:
    keep = ("kind", "liquid", "budget_account", "hidden", "goal", "availability")
    out = {}
    for a in account_list.accounts(conn):
        out[a["id"]] = plain(
            {
                **{k: a[k] for k in keep},
                "currency": a["balance"]["currency"],
                "balance": a["balance"],
                "value": a["value"],
                "target": a["target"],
                "missing_prices": a["missing_prices"],
                "last_booking": a["last_booking"],
                "last_clbd": a["last_clbd"],
            }
        )
    return out


def _performance(conn: Connection, as_of: str) -> dict[str, Any] | None:
    eng = perf_lines.engine_for(conn, as_of)
    if eng is None:
        return None
    found: dict[str, Any] = plain(performance.report(eng, None, None, None, STEP))
    return found


def _budget(conn: Connection, as_of: str) -> dict[str, Any]:
    month = period.month_of(date.fromisoformat(as_of))
    months = [*previous_months(month, MONTHS - 1), month]
    return {m: plain(totals.summary(conn, m, aggregates_only=False)) for m in months}


def sections(conn: Connection, as_of: str) -> dict[str, Any]:
    """Les agrégats figés, par section ; chacune se lit seule dans un écart."""
    return {
        "currency": base_currency(),
        "month_start_day": period.start_day(),
        "counts": _counts(conn),
        "valuation": _valuation(conn, as_of),
        "snapshots": _snapshots(conn),
        "accounts": _accounts(conn),
        "holdings": plain(holdings.holdings(conn, as_of)),
        "performance": _performance(conn, as_of),
        "reconcile": plain(reconcile.summary(conn, as_of)),
        "budget": _budget(conn, as_of),
        "debts": plain(debts.items(conn, as_of)),
    }


@dataclass(frozen=True)
class Golden:
    as_of: str
    created_at: str
    hub_version: str
    sections: dict[str, Any]

    @property
    def digest(self) -> str:
        return canonical.sha256_hex(self.sections)

    def public(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "as_of": self.as_of,
            "created_at": self.created_at,
            "hub_version": self.hub_version,
            "digest": self.digest,
            "sections": self.sections,
        }


def build(engine: Engine, as_of: date) -> Golden:
    with engine.connect() as conn:
        found = sections(conn, as_of.isoformat())
    return Golden(as_of.isoformat(), now_iso(), hub.__version__, found)


def save(golden: Golden, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(golden.public(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    )
    return path


def load(path: Path) -> Golden:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GoldenError(f"étalon illisible : {path}") from exc
    if (
        not isinstance(raw, dict)
        or raw.get("version") != VERSION
        or not isinstance(raw.get("sections"), dict)
    ):
        raise GoldenError(f"pas un étalon de version {VERSION} : {path}")
    golden = Golden(
        str(raw.get("as_of", "")),
        str(raw.get("created_at", "")),
        str(raw.get("hub_version", "")),
        raw["sections"],
    )
    if golden.digest != raw.get("digest"):
        raise GoldenError(f"étalon modifié depuis sa création : {path}")
    try:
        date.fromisoformat(golden.as_of)
    except ValueError:
        raise GoldenError(f"date de l'étalon illisible : {path}") from None
    return golden


def latest(folder: Path) -> Path | None:
    """Le dernier étalon écrit dans `folder` (par nom, donc par date), ou None."""
    found = sorted(folder.glob("finance-*.json")) if folder.is_dir() else []
    return found[-1] if found else None


def _flatten(value: Any, prefix: str, out: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        for k in sorted(value):
            _flatten(value[k], f"{prefix}/{k}" if prefix else str(k), out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(v, f"{prefix}/{i}", out)
    else:
        out[prefix] = value
    return out


@dataclass(frozen=True)
class Difference:
    path: str  # section/clé/…/clé
    before: Any
    after: Any


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[Difference]:
    a, b = _flatten(before, "", {}), _flatten(after, "", {})
    return [
        Difference(k, a.get(k), b.get(k))
        for k in sorted(a.keys() | b.keys())
        if a.get(k) != b.get(k)
    ]


@dataclass(frozen=True)
class Check:
    golden: Golden
    now: Golden
    differences: list[Difference]

    @property
    def ok(self) -> bool:
        return not self.differences

    def public(self) -> dict[str, Any]:
        by_section: dict[str, int] = {}
        for d in self.differences:
            section = d.path.split("/", 1)[0]
            by_section[section] = by_section.get(section, 0) + 1
        return {
            "ok": self.ok,
            "as_of": self.golden.as_of,
            "golden_version": self.golden.hub_version,
            "hub_version": self.now.hub_version,
            "differences": len(self.differences),
            "by_section": by_section,
            "examples": [vars(d) for d in self.differences[:EXAMPLES]],
        }


def check(engine: Engine, golden: Golden) -> Check:
    """Les mêmes agrégats, recalculés à la date de l'étalon ; une table apparue depuis n'est
    pas un écart, un chiffre de performance apparu depuis (le plus haut de la courbe) non plus."""
    now = build(engine, date.fromisoformat(golden.as_of))
    known = golden.sections.get("counts", {})
    current = {
        **now.sections,
        "counts": {k: v for k, v in now.sections["counts"].items() if k in known},
    }
    was, perf = golden.sections.get("performance"), now.sections.get("performance")
    if isinstance(was, dict) and isinstance(perf, dict):
        current["performance"] = {k: v for k, v in perf.items() if k in was}
    return Check(golden, now, diff(golden.sections, current))
