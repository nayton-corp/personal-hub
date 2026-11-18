"""Abonnements repérés corrigés par la personne : renommer, changer de catégorie, retirer et
remettre (set_recurring), relancer la recherche ; « À venir » ne liste que les charges fixes,
datées par les abonnements qui y sont rangés ; noms tirés des libellés bancaires."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from hub.core import proposals
from hub.core.context import HubContext
from hub.domains.finance.classement.app import recurring, upcoming
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    year,
)
from tests.finance.test_double_sas import APP, accept, create
from tests.finance.test_finance_api import app_session, token

TODAY = date(2026, 10, 27)


def _refresh(fin: FinanceDomain) -> dict[str, str]:  # noqa: F811
    """Recalcule les abonnements ; nom repéré → clé."""
    with begin_immediate(fin.engine()) as conn:
        recurring.refresh(conn, TODAY)
        return {
            str(r[1]): str(r[0]) for r in conn.execute(text("SELECT key, label FROM recurring"))
        }


def _listing(fin: FinanceDomain) -> Any:  # noqa: F811
    with fin.engine().connect() as conn:
        return recurring.listing(conn, TODAY, aggregates_only=False)


def test_bank_labels_become_readable_names() -> None:
    raw = "Paiement 04.11.2026 17:14 AMAZON PAYMENTS Numéro de carte: 5354******3169 Mont"
    assert recurring.tidy(raw) == "Amazon Payments"
    assert recurring.tidy("NETFLIX.COM 12345") == "Netflix.com"
    assert recurring.tidy("Hostpoint AG") == "Hostpoint AG"
    assert recurring.tidy("123456") == "123456"  # rien de lisible : le libellé tel quel


def test_upcoming_lists_fixed_categories_dated_by_their_subscriptions(
    year: FinanceDomain,  # noqa: F811
) -> None:
    _refresh(year)
    with year.engine().connect() as conn:
        dues = upcoming.month_dues(conn, "2026-10", TODAY)
    assert {d.kind for d in dues} == {"fixed"}
    assert all(d.name != "Bistrot Fictif" for d in dues)  # un abonnement d'une catégorie variable
    rent = next(d for d in dues if d.category == "logement")
    assert rent.via == "Régie Fictive"


def test_a_subscription_is_corrected_removed_and_restored_across_recomputes(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    keys = _refresh(year)
    bistrot = keys["Bistrot Fictif"]
    params = {"key": bistrot, "label": "Le bistrot", "category_id": "alimentation"}
    assert accept(ctx, create(ctx, "set_recurring", params)).status == "applied"
    _refresh(year)  # la détection repasse : la correction reste
    item = next(x for x in _listing(year)["items"] if x["key"] == bistrot)
    assert (item["label"], item["found_label"], item["category"]) == (
        "Le bistrot",
        "Bistrot Fictif",
        "alimentation",
    )
    before = _listing(year)["count"]
    hide = create(ctx, "set_recurring", {**params, "hidden": True})
    assert "pas un abonnement" in hide.preview["summary"]
    assert accept(ctx, hide).status == "applied"
    after = _listing(year)
    assert after["count"] == before - 1
    assert [x["key"] for x in after["removed"]] == [bistrot]
    assert all(x["key"] != bistrot for x in after["items"])
    with ctx.core.engine.connect() as conn:
        fresh = proposals.get(conn, hide.id)
    assert proposals.revert(ctx, APP, fresh, None).status == "applied"
    back = _listing(year)
    assert back["removed"] == []
    assert next(x for x in back["items"] if x["key"] == bistrot)["label"] == "Le bistrot"


def test_a_removed_subscription_no_longer_dates_its_fixed_category(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    regie = _refresh(year)["Régie Fictive"]
    accept(ctx, create(ctx, "set_recurring", {"key": regie, "hidden": True}))
    with year.engine().connect() as conn:
        rent = next(
            d for d in upcoming.month_dues(conn, "2026-10", TODAY) if d.category == "logement"
        )
    assert rent.via is None


def test_unknown_or_bad_corrections_are_refused(
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    keys = _refresh(year)
    from hub.core.errors import Problem

    with pytest.raises(Problem, match="inconnu"):
        create(ctx, "set_recurring", {"key": "nulle part|x|CHF"})
    with pytest.raises(Problem, match="pas une catégorie de dépense"):
        create(ctx, "set_recurring", {"key": keys["Bistrot Fictif"], "category_id": "salaire"})
    with begin_immediate(year.engine()) as conn:
        conn.execute(
            text("INSERT INTO recurring_choices (key, hidden, created_at) VALUES ('k', 0, 'x')")
        )
    with pytest.raises(IntegrityError, match="append_only"), begin_immediate(year.engine()) as conn:
        conn.execute(text("DELETE FROM recurring_choices"))


def test_search_again_is_for_the_app_only(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    path = "/api/finance/recurring/refresh"
    assert client.post(path, headers=token(ctx, "brain=finance")).status_code in (401, 403)
    app_session(ctx, client)
    r = client.post(path)
    assert r.status_code == 200
    assert {x["label"] for x in r.json()["items"]} >= {"Régie Fictive", "Bistrot Fictif"}
