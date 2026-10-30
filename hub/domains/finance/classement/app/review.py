"""Écritures à revoir (ticket L1-10) : les écritures sans catégorie, ou classées par une règle
fourre-tout, regroupées par contrepartie avec les catégories déjà choisies pour elle."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.registre.app import ledger
from hub.domains.finance.registre.model import merchant
from hub.domains.finance.registre.model.amounts import (
    UNCATEGORIZED,
    money,
)
from hub.kernel.text import normalize

REVIEW_IDS = 50  # identifiants rendus par groupe : de quoi proposer un lot de recatégorisations


def _direction(amounts: list[int]) -> str:
    if all(a < 0 for a in amounts):
        return "debit"
    if all(a > 0 for a in amounts):
        return "credit"
    return "any"


REVIEW_HISTORY = 3  # catégories passées proposées en premier
REVIEW_SAMPLES = 10  # écritures montrées en dépliant un groupe dans l'app


def _distinct(values: list[str | None], n: int = 3) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
        if len(seen) == n:
            break
    return seen


# écriture classée par une règle « tout le reste » (motif vide, sans compte) : « Autres revenus »
# pour tout crédit inconnu. Elle compte comme classée, mais « À classer » la montre à confirmer.
CATCH_ALL = (
    "vc.source = 'rule' AND r.field = 'search_text' AND trim(r.pattern) = '' "
    "AND r.account_id IS NULL"
)


def review_key(counterparty: str | None, label: str) -> str:
    """Groupe d'« À classer » : le commerçant lu dans le libellé (paiements par carte, TWINT),
    sinon la contrepartie, sinon le libellé. Sans vraie contrepartie, on groupe par libellé : un
    nom de remplissage réunirait des marchands sans rapport, et « Toujours » en ferait une règle
    beaucoup trop large. La clé est un morceau du texte de l'écriture : motif d'une règle."""
    return merchant.key(label) or normalize(ledger.party(counterparty) or label) or "(inconnu)"


def _past_categories(conn: Connection, keys: set[str]) -> dict[str, list[str]]:
    """Pour chaque groupe d'« À classer », les catégories que ses écritures déjà classées ont
    reçues (à la main ou par une règle précise), par nombre d'écritures décroissant."""
    if not keys:
        return {}
    rows = conn.execute(
        text(
            "SELECT e.counterparty, e.label, vc.category_id FROM entries e "
            "JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
            "LEFT JOIN categorizations c ON c.seq = vc.categorization_seq "
            "LEFT JOIN rules r ON r.id = c.rule_id "
            "WHERE e.kind = 'movement' AND vc.category_id IS NOT NULL "
            f"AND vc.category_id != :uncat AND NOT ({CATCH_ALL})"
        ),
        {"uncat": UNCATEGORIZED},
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for counterparty, label, category in rows:
        key = review_key(counterparty, label)
        if key in keys:
            per = counts.setdefault(key, {})
            per[category] = per.get(category, 0) + 1
    return {k: sorted(v, key=lambda c: (-v[c], c)) for k, v in counts.items()}


def review(conn: Connection, limit: int = 100) -> list[dict[str, Any]]:
    """Écritures sans catégorie (puis celles d'une règle « tout le reste »), groupées par
    commerçant ou contrepartie, avec de quoi décider : libellés bancaires, communications,
    comptes, période et fourchette des montants."""
    rows = conn.execute(
        text(
            "SELECT e.counterparty, e.label, e.currency, e.amount_minor, e.id, e.account_id, "
            "e.booking_date, e.remittance, e.bank_tx_code, vc.category_id FROM entries e "
            "LEFT JOIN v_entry_shown vc ON vc.entry_seq = e.seq "
            "LEFT JOIN categorizations c ON c.seq = vc.categorization_seq "
            "LEFT JOIN rules r ON r.id = c.rule_id "
            "WHERE e.kind = 'movement' AND (vc.category_id IS NULL OR ("
            f"{CATCH_ALL}))"
            "ORDER BY e.booking_date DESC, e.seq DESC"
        )
    ).fetchall()
    groups: dict[tuple[str, str, str | None], list[Any]] = {}
    for r in rows:
        groups.setdefault((review_key(r[0], r[1]), r[2], r[9]), []).append(r)
    history = _past_categories(conn, {k for k, _c, _g in groups})
    out: list[dict[str, Any]] = []
    for (key, ccy, guess), v in groups.items():
        amounts = [int(r[3]) for r in v]
        out.append(
            {
                "key": f"{key}|{ccy}|{guess or ''}",
                "counterparty": key,
                # classée d'office par une règle « tout le reste » : à confirmer
                "guess": guess,
                # catégories déjà données à ce commerçant, la plus fréquente d'abord
                "history": [c for c in history.get(key, []) if c != guess][:REVIEW_HISTORY],
                "count": len(v),
                "total": money(sum(amounts), ccy),
                "direction": _direction(amounts),
                "entry_ids": [r[4] for r in v[:REVIEW_IDS]],
                "first_date": v[-1][6],
                "last_date": v[0][6],
                "min": money(min(amounts, key=abs), ccy),
                "max": money(max(amounts, key=abs), ccy),
                "accounts": _distinct([r[5] for r in v], 5),
                "labels": _distinct([r[1] for r in v]),
                "remittances": _distinct([r[7] for r in v]),
                "bank_tx_codes": _distinct([r[8] for r in v]),
                "samples": [
                    {
                        "id": r[4],
                        "account_id": r[5],
                        "booking_date": r[6],
                        "amount": money(int(r[3]), ccy),
                        "label": r[1],
                        "remittance": r[7],
                    }
                    for r in v[:REVIEW_SAMPLES]
                ],
            }
        )
    out.sort(key=lambda g: (g["guess"] is not None, -g["count"], g["counterparty"]))
    return out[:limit]
