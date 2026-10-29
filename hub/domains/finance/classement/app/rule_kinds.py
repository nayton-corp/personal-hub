"""Propositions de règles (ticket L3-02) : créer une règle (l'aperçu montre les écritures
touchées), en désactiver une, installer un pack."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Connection, text

from hub.core.domain import Preview
from hub.domains.finance.classement.app import packs, rules
from hub.domains.finance.registre.app.kinds import (
    SAMPLE,
    Params,
    Slug,
    bad,
    category_row,
    entry_brief,
    fp,
    totals_by_currency,
)
from hub.kernel.ids import new_id
from hub.kernel.text import mask_iban

if TYPE_CHECKING:
    pass


# à priorité égale, l'identifiant départage : « user- » trie après « legacy- », « seed- » et
# « system- », et un ULID plus récent après les plus anciens. Une règle créée perd donc les ex
# aequo, dans l'aperçu (« ~ » trie après tout ULID) comme une fois appliquée.
USER_RULE_PREFIX = "user-"
PREVIEW_RULE_ID = f"{USER_RULE_PREFIX}~"


class CreateRule(Params):
    field: Literal["search_text", "counterparty_iban", "bank_tx_code"] = "search_text"
    pattern: str = Field(max_length=120)
    direction: Literal["any", "debit", "credit"] = "any"
    category_id: Slug
    priority: int = Field(default=50, ge=1, le=10_000)
    # règle d'un seul compte ; son motif peut être vide : « tout débit de ce compte »
    account_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _pattern(self) -> CreateRule:
        try:
            value = rules.normalize_pattern(self.field, self.pattern)
        except rules.RuleError as exc:
            raise ValueError(str(exc)) from None
        short = self.field == "search_text" and len(value.strip()) < 2
        if short and (self.account_id is None or value.strip()):
            raise ValueError("motif de deux caractères au moins")
        return self

    def normalized(self) -> str:
        return rules.normalize_pattern(self.field, self.pattern)


class CreateRuleHandler:
    def _rule(self, params: CreateRule, rule_id: str = "new") -> rules.Rule:
        return rules.Rule(
            rule_id,
            params.field,
            params.normalized(),
            params.direction,
            params.category_id,
            params.priority,
            account_id=params.account_id,
        )

    def _changes(self, conn: Connection, params: CreateRule, rule_id: str) -> list[rules.Change]:
        rule = self._rule(params, rule_id)
        current = rules.load(conn)
        return rules.changes(current.with_rule(rule), rules.candidates(conn), only=rule)

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, CreateRule)  # noqa: S101
        name, _grp = category_row(conn, params.category_id)
        account = None
        if params.account_id is not None:
            account = conn.execute(
                text("SELECT name FROM accounts WHERE id = :i"), {"i": params.account_id}
            ).scalar()
            if account is None:
                raise bad(f"compte inconnu : {params.account_id}")
        found = self._changes(conn, params, PREVIEW_RULE_ID)
        items = [(c.current.amount_minor, c.current.currency) for c in found]
        sample = _sample(conn, [c.current.entry_seq for c in found[:SAMPLE]])
        shape = {"search_text": "texte", "counterparty_iban": "IBAN", "bank_tx_code": "code"}
        motif = mask_iban(params.normalized()) if params.field == "counterparty_iban" else None
        what = f"{shape[params.field]} « {motif or params.normalized().strip()} »"
        if account is not None:
            sens = {"debit": "débit", "credit": "crédit", "any": "mouvement"}[params.direction]
            what = (
                f"« {account} » : {f'{what}, ' if params.normalized().strip() else ''}tout {sens}"
            )
        return Preview(
            summary=f"Règle {what} → {name} : {len(found)} écriture{'s' if len(found) > 1 else ''}",
            details={
                "count": len(found),
                "totals": totals_by_currency(items),
                "entries": sample,
                "to_category": params.category_id,
                "rules_version": rules.version(conn),
            },
            # les écritures touchées et leur état, pas la version globale des règles : une autre
            # règle validée dans le même lot (un autre commerçant) ne rend pas celle-ci périmée
            fingerprint=fp(
                "create_rule",
                sorted((c.current.entry_id, c.current.categorization_seq or 0) for c in found),
            ),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, CreateRule)  # noqa: S101
        rule_id = f"{USER_RULE_PREFIX}{new_id()}"
        found = self._changes(conn, params, rule_id)
        rule = rules.insert_rule(
            conn,
            id=rule_id,
            field=params.field,
            pattern=params.normalized(),
            direction=params.direction,
            category_id=params.category_id,
            priority=params.priority,
            proposal_id=proposal_id,
            account_id=params.account_id,
        )
        version = rules.bump_version(conn)
        changed = rules.apply_changes(
            conn, [rules.Change(c.current, rule) for c in found], proposal_id
        )
        return {"rule_id": rule.id, "changed": changed, "rules_version": version}


def _sample(conn: Connection, seqs: list[int]) -> list[dict[str, Any]]:
    if not seqs:
        return []
    marks = ",".join(f":s{i}" for i in range(len(seqs)))
    sql = (
        "SELECT id, booking_date, amount_minor, currency, counterparty, label FROM entries "
        f"WHERE seq IN ({marks}) ORDER BY booking_date DESC"
    )
    rows = conn.execute(
        text(sql),
        {f"s{i}": s for i, s in enumerate(seqs)},
    ).fetchall()
    return [entry_brief(r) for r in rows]


class DisableRule(Params):
    rule_id: str = Field(min_length=3, max_length=60)


class DisableRuleHandler:
    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, DisableRule)  # noqa: S101
        rule = rules.get_rule(conn, params.rule_id)
        if rule is None or not rule.active:
            raise bad("règle inconnue ou déjà désactivée")
        if rule.id.startswith(rules.SYSTEM_PREFIX):
            raise bad("une règle système ne se désactive pas")
        name, _ = category_row(conn, rule.category_id)
        used = conn.execute(
            text("SELECT count(*) FROM categorizations WHERE rule_id = :r"), {"r": rule.id}
        ).scalar_one()
        return Preview(
            summary=f"Désactiver la règle « {rule.pattern.strip() or '*'} » → {name}",
            details={"rule_id": rule.id, "categorizations_kept": int(used)},
            fingerprint=fp("disable_rule", rules.version(conn), rule.id),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, DisableRule)  # noqa: S101
        rules.set_active(conn, params.rule_id, False)
        return {"rule_id": params.rule_id, "rules_version": rules.bump_version(conn)}


class InstallPack(Params):
    name: Slug


def _pack(name: str) -> packs.Pack:
    found = packs.available().get(name)
    if found is None:
        raise bad(f"pack inconnu : {name}")
    return found


class InstallPackHandler:
    """Installe ou met à jour un pack livré avec le hub ; ses règles catégorisent aussitôt les
    écritures sans catégorie. Une règle déjà présente sous une autre origine n'est pas doublée."""

    def preview(self, conn: Connection, params: BaseModel) -> Preview:
        assert isinstance(params, InstallPack)  # noqa: S101
        pack = _pack(params.name)
        report = packs.install(conn, pack, dry_run=True)
        before = packs.installed(conn).get(pack.name)
        verb = "Mettre à jour" if before is not None else "Installer"
        return Preview(
            summary=(
                f"{verb} le pack « {pack.label} » v{pack.version} : {report.added} règles, "
                f"{report.categories_added} catégories"
            ),
            details=report.public(),
            fingerprint=fp("install_pack", rules.version(conn), pack.name, pack.version, before),
        )

    def apply(self, conn: Connection, params: BaseModel, proposal_id: str) -> dict[str, Any]:
        assert isinstance(params, InstallPack)  # noqa: S101
        return packs.install(conn, _pack(params.name)).public()
