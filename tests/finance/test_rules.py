"""L3-01 : moteur de règles, reprise de `bcf_aggregate.py` et de `bcf_rules.json`."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from hub.core.db import begin_immediate
from hub.domains.finance import catalog, legacy, rules
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import IBAN, IBAN_2, Stmt, Tx, camt053
from tests.finance.conftest import (
    add_account,
    open_account,
    ready_account,
    rows,
    without_seed_rules,
)
from tests.support import legacy_bcf_aggregate as old

D = date(2026, 10, 1)


def target(text_: str, amount: int = -100, iban: str | None = None, code: str | None = None):  # type: ignore[no-untyped-def]
    return rules.Target(amount, text_, iban, code, IBAN)


def rule(
    id_: str, pattern: str, category: str = "divers", prio: int = 100, **kw: str
) -> rules.Rule:
    return rules.Rule(
        id_,
        kw.get("field", "search_text"),
        rules.normalize_pattern(kw.get("field", "search_text"), pattern),
        kw.get("direction", "any"),
        category,
        prio,
    )


# --- moteur -----------------------------------------------------------------------------------


def test_priority_settles_conflicts() -> None:
    a = rule("a", "migros", "alimentation", prio=100)
    b = rule("b", "migros", "restaurants", prio=50)
    rs = rules.RuleSet([a, b])
    assert rs.winner(target("migros resto")) == b
    # à priorité égale, l'identifiant départage, toujours de la même façon
    c = rule("c", "migros", "shopping", prio=50)
    assert rules.RuleSet([c, a, b]).winner(target("migros")) == b
    assert rules.RuleSet([c, a]).winner(target("migros")) == c


def test_direction_field_and_word_edges() -> None:
    credit = rule("c", "rembours", "remboursements", direction="credit")
    debit = rule("d", "rembours", "divers", direction="debit")
    rs = rules.RuleSet([credit, debit])
    assert rs.winner(target("remboursement", 500)) == credit
    assert rs.winner(target("remboursement", -500)) == debit
    assert rs.winner(target("remboursement", 0)) is None
    # une espace en fin de motif est une limite de mot, y compris en fin de texte
    bar = rule("bar", "bar ", "restaurants")
    assert rules.normalize_pattern("search_text", "Bar ") == "bar "
    assert rules.RuleSet([bar]).winner(target("le bar")) == bar
    assert rules.RuleSet([bar]).winner(target("barbier")) is None
    # accents et majuscules ne comptent pas
    assert rules.RuleSet([rule("r", "Régie")]).winner(target("regie du centre")) is not None
    iban = rule("i", "ch44 3199 9123 0008 8901 2", field="counterparty_iban")
    assert iban.pattern == "CH4431999123000889012"
    assert rules.RuleSet([iban]).winner(target("x", iban="CH4431999123000889012")) == iban
    code = rule("k", "pmnt/ccrd", field="bank_tx_code")
    assert rules.RuleSet([code]).winner(target("x", code="PMNT/CCRD/POSD")) == code
    catch_all = rule("all", "", "autres-revenus", direction="credit")
    assert rules.RuleSet([catch_all]).winner(target("n'importe quoi", 1)) == catch_all
    assert rules.RuleSet([catch_all]).winner(target("n'importe quoi", -1)) is None


def test_own_account_rule() -> None:
    own = rules.Rule("system-transfer-own", "own_account", "*", "any", "transfer-own", 0)
    rs = rules.RuleSet([own], {IBAN, IBAN_2})
    assert rs.winner(target("x", iban=IBAN_2)) == own
    assert rs.winner(target("x", iban=IBAN)) is None  # le compte lui-même
    assert rs.winner(target("x")) is None


def test_bad_patterns() -> None:
    with pytest.raises(rules.RuleError):
        rules.normalize_pattern("counterparty_iban", " ")
    with pytest.raises(rules.RuleError):
        rules.normalize_pattern("bank_tx_code", "")
    with pytest.raises(rules.RuleError):
        rules.normalize_pattern("nope", "x")
    assert rules.normalize_pattern("own_account", "anything") == "*"
    assert rules.normalize_pattern("search_text", "   ") == ""


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 300), st.sampled_from("abc")), min_size=1, max_size=8))
def test_lowest_priority_always_wins(spec: list[tuple[int, str]]) -> None:
    rs = [rule(f"r{i}{c}", "commun", "divers", prio=p) for i, (p, c) in enumerate(spec)]
    won = rules.RuleSet(rs).winner(target("texte commun"))
    assert won == min(rs, key=rules.Rule.key)


# --- base et import ---------------------------------------------------------------------------


def second_account(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        catalog.add_account(conn, institution="BCF", name="Épargne", iban=IBAN_2)


def import_stmt(finance: FinanceDomain, txs: list[Tx], **kw: object) -> None:
    data = camt053(Stmt(Decimal("1000.00"), D, txs, **kw))  # type: ignore[arg-type]
    finance.importer.process([Incoming("r.xml", data)])


def categories(finance: FinanceDomain) -> dict[str, str | None]:
    """Contrepartie -> catégorie courante (fixtures : une contrepartie par écriture)."""
    found = rows(
        finance,
        "SELECT e.counterparty, vc.category_id FROM entries e "
        "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq WHERE e.kind = 'movement'",
    )
    return {str(r[0]): r[1] for r in found}  # type: ignore[misc]


def test_import_categorizes_with_seed_rules(finance: FinanceDomain) -> None:
    a = ready_account(finance)
    second_account(finance)
    import_stmt(
        finance,
        [
            Tx("85.30", True, D, counterparty="Migros Fictif"),
            Tx("2500.00", False, D, counterparty="Employeur Fictif SA", label="Salaire octobre"),
            Tx("100.00", True, D, counterparty="Moi", counterparty_iban=IBAN_2),
            Tx("500.00", True, D, counterparty="Terzo Vorsorgestiftung"),
            Tx("12.00", True, D, counterparty="Inconnu Fictif"),
            Tx("30.00", False, D, counterparty="Ami Fictif", label="Crédit TWINT"),
        ],
    )
    assert categories(finance) == {
        "Migros Fictif": "alimentation",
        "Employeur Fictif SA": "salaire",
        "Moi": "transfer-own",
        "Terzo Vorsorgestiftung": "epargne-3a",
        "Inconnu Fictif": None,
        "Ami Fictif": "autres-revenus",
    }
    sources = rows(finance, "SELECT DISTINCT source FROM categorizations")
    assert sources == [("rule",)]
    assert a.id


def test_rules_never_override_a_human(finance: FinanceDomain) -> None:
    ready_account(finance)
    import_stmt(finance, [Tx("10.00", True, D, counterparty="Coop Fictif")])
    with begin_immediate(finance.engine()) as conn:
        seq = conn.execute(text("SELECT seq FROM entries WHERE kind = 'movement'")).scalar_one()
        conn.execute(
            text("INSERT INTO categories (id, name, grp) VALUES ('cadeau-x', 'Cadeau', 'variable')")
        )
        from hub.domains.finance import ledger

        ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": seq,
                "category_id": "cadeau-x",
                "source": "user",
                "rule_id": None,
                "proposal_id": None,
                "created_at": "2026-10-27T10:00:00.000Z",
            },
        )
        rules.insert_rule(
            conn,
            id="user-z",
            field="search_text",
            pattern="coop",
            direction="any",
            category_id="shopping",
            priority=1,
        )
        assert rules.run(conn) == 0
    assert categories(finance) == {"Coop Fictif": "cadeau-x"}


def test_insert_rule_checks(finance: FinanceDomain) -> None:
    with begin_immediate(finance.engine()) as conn:
        kw = {"id": "x", "pattern": "p", "direction": "any", "priority": 1}
        with pytest.raises(rules.RuleError):
            rules.insert_rule(conn, field="own_account", category_id="divers", **kw)  # type: ignore[arg-type]
        with pytest.raises(rules.RuleError):
            rules.insert_rule(conn, field="search_text", category_id="nope", **kw)  # type: ignore[arg-type]
        with pytest.raises(rules.RuleError):
            rules.insert_rule(
                conn,
                id="x",
                field="search_text",
                pattern="p",
                direction="sideways",
                category_id="divers",
                priority=1,
            )
        v = rules.version(conn)
        assert rules.bump_version(conn) == v + 1
        assert rules.get_rule(conn, "nope") is None


# --- équivalence avec bcf_aggregate.py (critère d'acceptation de L3-01) -----------------------


def legacy_category(kind: str, cat: str) -> str | None:
    if cat == "Non catégorisé":
        return None
    if kind == "transfer":
        if cat == "Entre mes comptes":
            return "transfer-own"
        return legacy.TRANSFER_MAP[cat][0]
    return legacy.CATEGORY_MAP[cat][0]


def fixture_txs() -> list[Tx]:
    """Une écriture par mot-clé de chaque liste, plus les cas codés en dur du script."""
    out: list[Tx] = []
    day = D
    cents = 101

    def add(debit: bool, counterparty: str, label: str = "Achat carte", **kw: object) -> None:
        nonlocal cents, day
        cents += 7
        out.append(
            Tx(
                f"{cents // 100}.{cents % 100:02d}",
                debit,
                day,
                counterparty=counterparty,
                label=label,
                **kw,
            )  # type: ignore[arg-type]
        )

    for kws in old.DEFAULT_RULES["categories"].values():
        for kw in kws:
            add(True, f"{kw.strip().upper()} Fictif".replace("  ", " "))
    for kws in old.DEFAULT_RULES["transfers"].values():
        for kw in kws:
            add(True, f"{kw.title()} Fictif", label="Ordre e-banking")
            add(False, f"{kw.title()} Fictif", label="Bonification")
    for word in ("Salaire", "Lohn", "Remboursement", "Refund", "Versement"):
        add(False, "Employeur Fictif", label=f"{word} octobre")
    add(True, "Jean Exemple", label="Débit TWINT")
    add(True, "Jeanne Exemple", label="Ordre permanent")
    add(True, "Personne Fictive", label="Virement")
    add(True, "Quelque Chose", label="Paiement")
    add(True, "Mon Épargne", counterparty_iban=IBAN_2)
    add(False, "Mon Épargne", counterparty_iban=IBAN_2)
    return out


def legacy_seeded(finance: FinanceDomain) -> None:
    """Les règles de l'ancien script à la place des packs, comme une base d'avant G2."""
    without_seed_rules(finance)
    with begin_immediate(finance.engine()) as conn:
        legacy.import_rules(conn, old.DEFAULT_RULES, run=False)


def test_same_categories_as_bcf_aggregate(finance: FinanceDomain, tmp_path: Path) -> None:
    legacy_seeded(finance)
    a = add_account(finance)
    open_account(finance, a, "2026-09-30", 100_000)
    second_account(finance)
    txs = fixture_txs()
    data = camt053(Stmt(Decimal("1000.00"), D, txs))
    finance.importer.process([Incoming("r.xml", data)])

    path = tmp_path / "r.xml"
    path.write_bytes(data)
    legacy_rules = copy.deepcopy(old.DEFAULT_RULES) | {"own_ibans": [IBAN_2]}
    _accounts, entries = old.entries_of(path)
    expected = {
        round(e["amount"] * 100): legacy_category(*old.categorize(e, legacy_rules, {IBAN_2}))
        for e in entries
    }
    got = {
        int(str(r[0])): r[1]
        for r in rows(
            finance,
            "SELECT e.amount_minor, vc.category_id FROM entries e "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq WHERE e.kind = 'movement'",
        )
    }
    assert len(got) == len(expected) == len(txs)
    diff = {k: (got[k], v) for k, v in expected.items() if got[k] != v}
    assert diff == {}
    # le jeu couvre bien chaque catégorie de l'ancien script
    assert set(expected.values()) >= {c[0] for c in legacy.CATEGORY_MAP.values()} - {
        "virements-particuliers"
    }


# --- reprise de bcf_rules.json ----------------------------------------------------------------


def test_convert_orders_like_the_script() -> None:
    specs, needed = legacy.convert(old.DEFAULT_RULES)
    prios = [s.priority for s in specs]
    assert prios == sorted(prios)
    assert {c.id for c in needed} >= {"epargne-3a", "abonnements", "a-qualifier", "crypto"}
    # « régie » et « regie » donnent un seul motif
    logement = [s.pattern for s in specs if s.category_id == "logement"]
    assert logement.count("regie") == 1
    with pytest.raises(legacy.LegacyError):
        legacy.convert({"categories": []})
    with pytest.raises(legacy.LegacyError):
        legacy.convert({"categories": {"X": "pas une liste"}})
    assert legacy.slug("Mes Projets & Co") == "mes-projets-co"
    assert legacy.slug("?") == "cat-x"


def test_import_legacy_merges_and_disables(finance: FinanceDomain) -> None:
    legacy_seeded(finance)
    ready_account(finance)
    import_stmt(
        finance,
        [
            Tx("10.00", True, D, counterparty="Chez Zorglub"),
            Tx("20.00", True, D, counterparty="Lidl Fictif"),
        ],
    )
    assert categories(finance)["Chez Zorglub"] is None
    data = copy.deepcopy(old.DEFAULT_RULES)
    data["categories"]["Restaurants & sorties"].append("chez zorglub")
    data["categories"]["Alimentation"].remove("lidl")
    data["categories"]["Jardin"] = ["pépinière"]
    data["own_ibans"] = ["CH00"]
    with begin_immediate(finance.engine()) as conn:
        before = rules.version(conn)
        report = legacy.import_rules(conn, data)
    assert report.rules_added == 2  # chez zorglub, pépinière
    assert report.rules_disabled == 1  # lidl
    assert report.categories_added == 1  # jardin
    assert report.own_ibans_ignored == 1
    assert report.version == before + 1
    assert report.categorized == 1
    got = categories(finance)
    assert got["Chez Zorglub"] == "restaurants"
    assert got["Lidl Fictif"] == "alimentation"  # la catégorisation déjà faite reste
    # rejouer le même fichier ne change rien
    with begin_immediate(finance.engine()) as conn:
        again = legacy.import_rules(conn, data)
    assert (again.rules_added, again.rules_disabled, again.categorized) == (0, 0, 0)
    assert rows(finance, "SELECT grp FROM categories WHERE id = 'jardin'") == [("variable",)]


def test_rules_cli(finance: FinanceDomain, tmp_path: Path) -> None:
    import json

    from typer.testing import CliRunner

    ready_account(finance)
    import_stmt(finance, [Tx("10.00", True, D + timedelta(1), counterparty="Chez Zorglub")])
    app = finance.cli()
    assert app is not None
    runner = CliRunner()
    listed = runner.invoke(app, ["rules", "list"]).stdout
    assert "system-transfer-own" in listed
    data = copy.deepcopy(old.DEFAULT_RULES)
    data["categories"]["Restaurants & sorties"].append("chez zorglub")
    path = tmp_path / "bcf_rules.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    out = runner.invoke(app, ["rules", "import-legacy", str(path)])
    assert out.exit_code == 0, out.stdout
    assert json.loads(out.stdout)["categorized"] == 1
    assert "Bistrot" not in out.stdout  # compteurs seulement
    assert json.loads(runner.invoke(app, ["rules", "run"]).stdout) == {"categorized": 0}
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert runner.invoke(app, ["rules", "import-legacy", str(bad)]).exit_code == 1
    assert "désactivée" not in runner.invoke(app, ["rules", "list"]).stdout
    assert runner.invoke(app, ["rules", "list", "--all"]).exit_code == 0
