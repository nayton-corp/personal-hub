"""Frais courants des fonds détenus (migration 0029) : ce que le TER coûte par an, et sur trente
ans.

Le TER vient de `fund_fees` (saisi par la proposition `set_fund_fee`, la dernière ligne d'un ISIN
fait foi). Un fonds sans TER connu est listé « frais inconnus » et reste hors des totaux : rien
n'est deviné. Coût par an : valeur détenue × TER. Coût sur trente ans : l'écart entre la valeur
finale sans frais et avec, pour la position d'aujourd'hui laissée telle quelle, au rendement
annuel supposé `ASSUMED_RETURN` avant frais ; un ordre de grandeur, dit comme tel à l'écran.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import valuation
from hub.domains.finance.patrimoine.app.fund_needs import is_fund
from hub.domains.finance.registre.app.kinds import Params, bad, fp
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id
from hub.kernel.money import DECIMAL_CONTEXT, Money, base_currency

YEARS = 30
ASSUMED_RETURN = Decimal("0.05")  # par an, avant frais
MAX_TER = Decimal("0.05")


def known(conn: Connection) -> dict[str, tuple[Decimal, str]]:
    """{ISIN : (TER par an, source)} : la dernière ligne posée fait foi."""
    out: dict[str, tuple[Decimal, str]] = {}
    for isin, ter, source in conn.execute(
        text("SELECT isin, ter, source FROM fund_fees ORDER BY created_at, id")
    ):
        out[str(isin)] = (Decimal(ter), str(source))
    return out


def _held(conn: Connection, on_date: str) -> dict[str, tuple[str, int]]:
    """{ISIN : (nom, valeur en devise de base)} des fonds détenus hors comptes crypto."""
    positions = valuation.Positions(conn)
    crypto = {r[0] for r in conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'"))}
    meta = {
        r[0]: (r[1], r[2]) for r in conn.execute(text("SELECT isin, kind, name FROM instruments"))
    }
    out: dict[str, tuple[str, int]] = {}
    for account_id in sorted(positions.accounts - crypto):
        for x in positions.lines(account_id, on_date):
            kind, name = meta.get(x.isin, (None, None))
            if not x.quantity or not is_fund(kind, name):
                continue
            out[x.isin] = (name or x.isin, out.get(x.isin, ("", 0))[1] + int(x.value))
    return out


def _pct(ter: Decimal) -> str:
    return format((ter * 100).normalize(), "f")


def cost_over(value: int, ter: Decimal, years: int = YEARS) -> int:
    """Ce que le TER retire à `value` en `years` ans, au rendement supposé avant frais."""
    with localcontext(DECIMAL_CONTEXT):
        free = (1 + ASSUMED_RETURN) ** years
        net = max(Decimal(0), 1 + ASSUMED_RETURN - ter) ** years
        return int((Decimal(value) * (free - net)).quantize(Decimal(1), ROUND_HALF_EVEN))


def summary(conn: Connection, on_date: str) -> dict[str, object]:
    ccy = base_currency()
    fees = known(conn)
    items: list[dict[str, object]] = []
    yearly = covered = unknown = later = 0
    for isin, (name, value) in sorted(_held(conn, on_date).items(), key=lambda kv: -kv[1][1]):
        fee = fees.get(isin)
        cost = None
        if fee is None:
            unknown += value
        else:
            with localcontext(DECIMAL_CONTEXT):
                cost = int((Decimal(value) * fee[0]).quantize(Decimal(1), ROUND_HALF_EVEN))
            yearly += cost
            covered += value
            later += cost_over(value, fee[0])
        items.append(
            {
                "isin": isin,
                "name": name,
                "value": Money(value, ccy).to_api(),
                "ter_pct": _pct(fee[0]) if fee else None,
                "source": fee[1] if fee else None,
                "yearly_cost": Money(cost, ccy).to_api() if cost is not None else None,
            }
        )
    return {
        "on_date": on_date,
        "currency": ccy,
        "items": items,
        "yearly_cost": Money(yearly, ccy).to_api(),
        "covered_value": Money(covered, ccy).to_api(),
        "unknown_value": Money(unknown, ccy).to_api(),
        "cost_over_years": Money(later, ccy).to_api(),
        "years": YEARS,
        "assumed_return_pct": _pct(ASSUMED_RETURN),
    }


class SetFundFee(Params):
    """Frais courants (TER) d'un fonds, en % par an, tels que l'émetteur les publie."""

    isin: str = Field(min_length=3, max_length=40)
    ter_pct: str = Field(pattern=r"^\d(\.\d{1,3})?$")  # « 0.2 » pour 0,20 % par an


class SetFundFeeHandler:
    @staticmethod
    def _check(conn: Connection, p: SetFundFee) -> tuple[str, Decimal, Decimal | None]:
        row = conn.execute(
            text("SELECT name FROM instruments WHERE isin = :i"), {"i": p.isin}
        ).first()
        if row is None:
            raise bad("fonds inconnu")
        ter = Decimal(p.ter_pct) / 100
        if ter > MAX_TER:
            raise bad("frais au-delà de 5 % par an : vérifie le chiffre")
        before = known(conn).get(p.isin)
        if before is not None and before[0] == ter:
            raise bad("aucun changement")
        return str(row[0] or p.isin), ter, before[0] if before else None

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SetFundFee)  # noqa: S101
        name, ter, before = self._check(conn, params)
        return Preview(
            summary=f"Frais de « {name} » : {_pct(ter)} % par an",
            details={**params.model_dump(), "previous_pct": _pct(before) if before else None},
            fingerprint=fp("set_fund_fee", params.isin, str(before)),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, SetFundFee)  # noqa: S101
        _name, ter, before = self._check(conn, params)
        conn.execute(
            text(
                "INSERT INTO fund_fees (id, isin, ter, source, proposal_id, created_at) "
                "VALUES (:id, :i, :t, 'user', :p, :at)"
            ),
            {
                "id": new_id(),
                "i": params.isin,
                "t": format(ter.normalize(), "f"),
                "p": proposal_id,
                "at": now_iso(),
            },
        )
        return {"isin": params.isin, "previous_pct": _pct(before) if before else None}
