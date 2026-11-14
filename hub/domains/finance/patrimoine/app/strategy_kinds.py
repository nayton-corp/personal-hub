"""Propositions sur les stratégies : en écrire ou en modifier une, répondre à une étape."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.patrimoine.app import (
    strategies,
    strategy_detect,
    strategy_history,
    strategy_text,
)
from hub.domains.finance.patrimoine.model import strategy as rules
from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.app.kinds import Params, bad, fp
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id, urn

SINCE_DAYS = 2 * 366
Amount = Annotated[int, Field(ge=100, le=100_000_000_000)]
SETTINGS = {
    "ladder": ("tiers",),
    "recurring": ("cadence", "day", "amount_minor"),
    "dip": ("drop_pct", "window_days", "amount_minor"),
}
STATUS_LABEL = {"active": "reprise", "paused": "en pause", "ended": "terminée"}
ANSWER_STATE = {"done": "done", "later": "later", "skip": "skipped"}
ANSWER_LABEL = {"done": "c'est fait", "later": "plus tard", "skip": "je passe"}


class Host(Protocol):
    """Ce que les handlers attendent du domaine (`FinanceDomain` le remplit)."""

    def today(self) -> date: ...


class TierIn(Params):
    at_pct: int = Field(ge=50, le=1000)  # niveau en % du prix d'achat (100 : sans perte)
    sell_pct: int = Field(ge=5, le=100)  # part de ce qui est tenu, à vendre


class SaveStrategy(Params):
    """Écrit une stratégie (sans `strategy_id` : `kind`, `scope` et les réglages du genre) ou
    change celle donnée ; un champ absent ne change pas. Le hub ne passe jamais d'ordre : il
    prévient quand une étape est atteinte. `ladder` (vendre par paliers, crypto seulement) :
    `tiers`, quatre au plus, dix points d'écart. `recurring` (achat régulier) : `cadence`, `day`
    (jour du mois 1 à 28, ou jour de la semaine 0 = lundi), `amount_minor`. `dip` (grosse
    baisse) : `drop_pct` (15 au moins), `window_days` (90 ou 365), `amount_minor`. `scope` : un
    instrument tenu (`CRYPTO:BTC`, un ISIN) ou, pour la crypto, `crypto:alt` (tout sauf bitcoin
    et stablecoins) ou `crypto:all`."""

    strategy_id: str | None = Field(default=None, min_length=1, max_length=40)
    kind: Literal["ladder", "recurring", "dip"] | None = None  # à la création
    scope: str | None = Field(default=None, min_length=1, max_length=40)  # à la création
    tiers: list[TierIn] | None = Field(default=None, min_length=1, max_length=rules.MAX_TIERS)
    cadence: Literal["monthly", "weekly"] | None = None
    day: int | None = Field(default=None, ge=0, le=28)
    amount_minor: Amount | None = None
    drop_pct: int | None = Field(default=None, ge=rules.MIN_DROP_PCT, le=90)
    window_days: Literal[90, 365] | None = None
    note: str | None = Field(default=None, max_length=200)  # « ensuite » ; "" efface
    status: Literal["active", "paused", "ended"] | None = None
    # achat régulier repéré par le hub : la première échéance de la série (création seulement) ;
    # les échéances passées sont posées d'après le journal
    since: date | None = None


def _settings(kind: str, p: SaveStrategy, current: dict[str, object]) -> dict[str, object]:
    """Les réglages du genre après la demande, vérifiés ; un réglage d'un autre genre est refusé."""
    given = p.model_dump(include={k for keys in SETTINGS.values() for k in keys}, exclude_none=True)
    foreign = sorted(set(given) - set(SETTINGS[kind]))
    if foreign:
        raise bad(f"réglages d'un autre genre : {', '.join(foreign)}")
    out = {**current, **given}
    missing = [k for k in SETTINGS[kind] if k not in out]
    if missing:
        raise bad(f"réglages requis : {', '.join(missing)}")
    if kind == "ladder":
        tiers = [
            rules.Tier(int(t["at_pct"]), int(t["sell_pct"])) for t in strategies._list(out["tiers"])
        ]
        problem = rules.tiers_problem(tiers)
        if problem:
            raise bad(f"paliers : {problem}")
        out["tiers"] = [{"at_pct": t.at_pct, "sell_pct": t.sell_pct} for t in sorted(tiers)]
    if kind == "recurring":
        day, weekly = int(str(out["day"])), out["cadence"] == "weekly"
        if not (0 <= day <= 6 if weekly else 1 <= day <= 28):
            raise bad("jour : 0 (lundi) à 6 pour chaque semaine, 1 à 28 pour chaque mois")
    return out


class SaveStrategyHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _wanted(
        self, conn: Connection, p: SaveStrategy
    ) -> tuple[strategies.Strategy | None, dict[str, object]]:
        """(la stratégie en place, les colonnes voulues)."""
        if p.strategy_id is None:
            if p.kind is None or p.scope is None:
                raise bad("champs requis pour une nouvelle stratégie : kind, scope")
            name = strategies.scope_name(conn, p.scope)
            if name is None:
                raise bad("cible inconnue")
            if p.kind == "ladder" and not strategies.is_crypto(p.scope):
                raise bad("vendre par paliers : crypto seulement (le prix d'achat y est suivi)")
            if p.kind != "ladder" and p.scope in rules.GROUPS:
                raise bad("un achat porte sur un instrument, pas sur un groupe")
            if p.kind != "recurring" and strategies.is_account(p.scope):
                raise bad("un compte ne se suit que par des versements réguliers")
            if p.status not in (None, "active"):
                raise bad("une nouvelle stratégie commence active")
            wanted: dict[str, object] = {
                "kind": p.kind,
                "scope": p.scope,
                "name": name,
                "params_json": canonical.dumps(_settings(p.kind, p, {})),
                "note": (p.note or "").strip() or None,
                "status": "active",
            }
            if p.since is not None:
                today = self.domain.today()
                if p.kind != "recurring":
                    raise bad("seul un achat régulier se reprend depuis le journal")
                if not (today - timedelta(days=SINCE_DAYS) <= p.since <= today):
                    raise bad("début hors des deux dernières années")
                wanted |= {"created_on": p.since.isoformat(), "origin": "detected"}
            return None, wanted
        if p.since is not None:
            raise bad("le début se choisit à la création")
        found = strategies.read(conn, p.strategy_id)
        if not found:
            raise bad("stratégie inconnue")
        s = found[0]
        if p.kind is not None or p.scope is not None:
            raise bad("le genre et la cible se choisissent à la création")
        if s.status == "ended":
            raise bad("stratégie terminée")
        wanted = {}
        params = canonical.dumps(_settings(s.kind, p, s.params))
        if params != canonical.dumps(s.params):
            wanted["params_json"] = params
        if p.note is not None and (p.note.strip() or None) != s.note:
            wanted["note"] = p.note.strip() or None
        if p.status is not None and p.status != s.status:
            wanted["status"] = p.status
        if not wanted:
            raise bad("aucun changement")
        return s, wanted

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, SaveStrategy)  # noqa: S101
        s, wanted = self._wanted(conn, params)
        details: dict[str, object] = {"strategy_id": params.strategy_id, "changes": sorted(wanted)}
        if s is None:
            kind, name, scope = str(wanted["kind"]), str(wanted["name"]), str(wanted["scope"])
            settings = _loads(wanted["params_json"])
            account = strategies.is_account(scope)
            said = strategy_text.phrase(kind, name, settings, account=account)
            summary = f"Nouvelle stratégie : {said}"
            if params.since is not None:
                summary, details["detected"] = _detected(
                    conn, self.domain.today(), scope, name, settings, params.since
                )
                details["phrase"] = said
            digest = fp("save_strategy", "absent", kind, scope)
        else:
            account = strategies.is_account(s.scope)
            settings = _loads(wanted.get("params_json")) or s.params
            said = strategy_text.phrase(s.kind, s.name, settings, account=account)
            summary = f"Stratégie modifiée : {said}"
            if "status" in wanted:
                summary = f"Stratégie {STATUS_LABEL[str(wanted['status'])]} : {said}"
            digest = fp("save_strategy", s.id, s.params, s.note, s.status)
        return Preview(summary=summary, details=details, fingerprint=digest)

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, SaveStrategy)  # noqa: S101
        s, wanted = self._wanted(conn, params)
        at = now_iso()
        if s is None:
            strategy_id = new_id()
            conn.execute(
                text(
                    "INSERT INTO strategies (id, kind, scope, name, params_json, note, status, "
                    "created_on, origin, created_at, updated_at) VALUES (:id, :kind, :scope, "
                    ":name, :params_json, :note, :status, :created_on, :origin, :at, :at)"
                ),
                {
                    "created_on": self.domain.today().isoformat(),
                    "origin": None,
                    **wanted,
                    "id": strategy_id,
                    "at": at,
                },
            )
            if wanted.get("origin") == "detected":  # les échéances passées, d'après le journal
                today = self.domain.today()
                strategy_history.backfill(
                    conn, strategies.read(conn, strategy_id)[0], strategies.Today(conn, today)
                )
        else:
            strategy_id = s.id
            sets = ", ".join(f"{c} = :{c}" for c in wanted)  # noms fixés par _wanted
            conn.execute(
                text(f"UPDATE strategies SET {sets}, updated_at = :at WHERE id = :i"),  # noqa: S608
                {**wanted, "at": at, "i": strategy_id},
            )
            if wanted.get("status") == "ended":  # une stratégie terminée n'attend plus rien
                conn.execute(
                    text(
                        "UPDATE strategy_steps SET state = 'skipped', closed_on = :on, "
                        "closed_by = 'user', proposal_id = :p, updated_at = :at "
                        "WHERE strategy_id = :i AND state IN ('open', 'later')"
                    ),
                    {
                        "on": self.domain.today().isoformat(),
                        "p": proposal_id,
                        "at": at,
                        "i": strategy_id,
                    },
                )
        ledger.append_event(conn, "strategy.changed", urn("finance", "strategy", strategy_id))
        return {"strategy_id": strategy_id, "created": s is None}


def _detected(
    conn: Connection, today: date, scope: str, name: str, p: dict[str, object], since: date
) -> tuple[str, dict[str, object]]:
    """Le titre d'une carte repérée par le hub et ce qu'il a vu au journal (échéance par
    échéance), pour que la carte montre ses preuves."""
    cadence, day, amount = str(p["cadence"]), int(str(p["day"])), int(str(p["amount_minor"]))
    now = strategies.Today(conn, today)
    seen = strategy_history.periods(now, scope, cadence, day, since)
    kept = sum(1 for x in seen if rules.settled(x.done, amount))
    every = "chaque semaine" if cadence == "weekly" else "chaque mois"
    shown = strategy_text.shown(amount)
    if strategies.is_account(scope):
        title = f"Versement régulier repéré : {shown} sur {name} {every}"
    else:
        title = f"DCA repéré : {shown} de {name} {every}"
    series = next((f.series for f in strategy_detect.candidates(conn, today, scope)), None)
    return title, {
        "since": since.isoformat(),
        # la série elle-même : nombre d'achats et écart des montants (une échéance peut en
        # compter deux, quand un achat en plus tombe dans sa période)
        "count": len(series.buys) if series else None,
        "low": series.low if series else None,
        "high": series.high if series else None,
        "cadence": cadence,
        "account": strategies.is_account(scope),
        "kept": kept,
        "periods": [{"due": x.due.isoformat(), "done": x.done} for x in seen],
    }


def _loads(raw: object) -> dict[str, object]:
    return json.loads(raw) if isinstance(raw, str) else {}


class AnswerStrategyStep(Params):
    """Répond à une étape atteinte d'une stratégie : `done` (c'est fait, même si le journal ne
    le montre pas encore), `later` (elle reste en attente, sans autre alerte), `skip` (je passe :
    l'étape est close, la stratégie continue)."""

    step_id: str = Field(min_length=1, max_length=40)
    answer: Literal["done", "later", "skip"]


class AnswerStrategyStepHandler:
    def __init__(self, domain: Host) -> None:
        self.domain = domain

    def _step(self, conn: Connection, p: AnswerStrategyStep) -> tuple[str, str, str]:
        """(stratégie, phrase, état en place) de l'étape, si elle attend encore une réponse."""
        row = conn.execute(
            text("SELECT strategy_id, state FROM strategy_steps WHERE id = :i"), {"i": p.step_id}
        ).first()
        if row is None:
            raise bad("étape inconnue")
        if row[1] not in strategies.PENDING:
            raise bad("étape déjà close")
        if ANSWER_STATE[p.answer] == row[1]:
            raise bad("aucun changement")
        s = strategies.read(conn, str(row[0]))[0]
        said = strategy_text.phrase(
            s.kind, s.name, s.params, account=strategies.is_account(s.scope)
        )
        return s.id, said, str(row[1])

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, AnswerStrategyStep)  # noqa: S101
        strategy_id, said, state = self._step(conn, params)
        return Preview(
            summary=f"Étape de stratégie, {ANSWER_LABEL[params.answer]} : {said}",
            details={"strategy_id": strategy_id, "step_id": params.step_id},
            fingerprint=fp("answer_strategy_step", params.step_id, state),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, object]:
        assert isinstance(params, AnswerStrategyStep)  # noqa: S101
        strategy_id, _said, _state = self._step(conn, params)
        closed = params.answer != "later"
        conn.execute(
            text(
                "UPDATE strategy_steps SET state = :s, closed_on = :on, closed_by = :by, "
                "proposal_id = :p, updated_at = :at WHERE id = :i"
            ),
            {
                "s": ANSWER_STATE[params.answer],
                "on": self.domain.today().isoformat() if closed else None,
                "by": "user" if closed else None,
                "p": proposal_id,
                "at": now_iso(),
                "i": params.step_id,
            },
        )
        ledger.append_event(conn, "strategy.changed", urn("finance", "strategy", strategy_id))
        return {
            "strategy_id": strategy_id,
            "step_id": params.step_id,
            "state": ANSWER_STATE[params.answer],
        }
