"""Invariants du registre (section 11), vérifiés sur des historiques fictifs aléatoires.

1. Idempotence : un relevé importé deux fois, ou deux relevés qui se chevauchent dans n'importe
   quel ordre, donnent exactement le même registre.
2. Conservation : OPBD + somme des écritures = CLBD, et le solde calculé à la date de CLBD égale
   CLBD.
3. Aucune perte : écritures insérées = transactions BOOK distinctes générées.
4. Immuabilité : la chaîne d'empreintes se vérifie après toute suite d'opérations.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import History, camt053, histories
from tests.finance.conftest import add_account, finance_settings, ledger_state, open_account, rows


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("template")
    d = FinanceDomain(finance_settings(root))
    d.migrate()
    d.engine().dispose()
    return root


@contextmanager
def fresh(template: Path, h: History) -> Iterator[FinanceDomain]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(template, root, dirs_exist_ok=True)
        d = FinanceDomain(finance_settings(root))
        a = add_account(d)
        opening = (h.start - timedelta(days=1)).isoformat()
        open_account(d, a, opening, int(h.opening * 100))
        try:
            yield d
        finally:
            d.engine().dispose()


def _state(d: FinanceDomain) -> list[tuple[object, ...]]:
    return ledger_state(d)


@st.composite
def overlapping(draw: st.DrawFn) -> tuple[History, int, int]:
    h = draw(histories())
    n = len(h.days)
    k = draw(st.integers(0, n - 2))  # A = jours [0, k]
    j = draw(st.integers(1, k + 1))  # B = jours [j, n-1], chevauche ou touche A
    return h, k, j


HYP = settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@HYP
@given(case=overlapping(), version=st.sampled_from(["04", "08"]))
def test_idempotence_conservation_no_loss(
    template: Path, case: tuple[History, int, int], version: str
) -> None:
    h, k, j = case
    a = Incoming("a.xml", camt053(h.export(0, k, "A"), version))
    b = Incoming(
        "b.xml", camt053(h.export(j, len(h.days) - 1, "B"), "04" if version == "08" else "08")
    )
    states = []
    for order in ([a, b], [b, a]):
        with fresh(template, h) as d:
            for f in order:  # deux passages séparés : B avant A doit attendre puis être rejoué
                d.importer.process([f])
            d.importer.process([a])  # le même fichier une seconde fois : doublon
            assert rows(d, "SELECT status FROM imports ORDER BY file_name") == [
                ("applied",),
                ("applied",),
            ]
            # aucune perte
            movements = rows(d, "SELECT count(*) FROM entries WHERE kind = 'movement'")
            assert movements == [(h.booked(),)]
            # conservation : chaque CLBD égale le solde calculé à sa date
            for on_date, amount in rows(
                d, "SELECT on_date, amount_minor FROM checkpoints WHERE kind = 'CLBD'"
            ):
                computed = rows(
                    d,
                    "SELECT sum(amount_minor) FROM entries WHERE booking_date <= :d",
                    d=on_date,
                )
                assert computed == [(amount,)]
            # immuabilité
            assert d.verify_ledger().ok
            states.append([s[2:] for s in _state(d)])
    assert states[0] == states[1]


@HYP
@given(h=histories())
def test_same_statement_twice_changes_nothing(template: Path, h: History) -> None:
    data = camt053(h.export(0, len(h.days) - 1))
    with fresh(template, h) as d:
        d.importer.process([Incoming("x.xml", data)])
        before = _state(d)
        d.importer.process([Incoming("x.xml", data)])
        d.importer.process([Incoming("y.xml", data + b"\n")])  # autre empreinte, même contenu
        assert _state(d) == before
        assert d.verify_ledger().ok
