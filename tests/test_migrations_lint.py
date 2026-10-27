"""Analyse statique des migrations et du code (section 9)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = "# ledger-migration: reviewed"
PROTECTED = (
    "entries",
    "categorizations",
    "categorization_lines",
    "notes",
    "checkpoints",
    "budgets",
    "tags",
    "taggings",
    "applied_proposals",
    "events",
    "journal",
    "trades",
    "holdings",
    "prices",
    "audit",
    "links",
)
_P = "|".join(PROTECTED)
FORBIDDEN = [
    re.compile(r"batch_alter_table"),
    re.compile(r"drop_table", re.I),
    re.compile(r"DROP\s+TABLE", re.I),
    re.compile(r"DROP\s+TRIGGER", re.I),
    re.compile(rf"UPDATE\s+({_P})\b", re.I),
    re.compile(rf"DELETE\s+FROM\s+({_P})\b", re.I),
]
# interdits partout, migrations et code : ils contournent les déclencheurs
REPLACE = [
    re.compile(rf"INSERT\s+OR\s+REPLACE\s+INTO\s+({_P})\b", re.I),
    re.compile(rf"REPLACE\s+INTO\s+({_P})\b", re.I),
    re.compile(rf"INTO\s+({_P})\b[^;]*ON\s+CONFLICT[^;]*DO\s+UPDATE", re.I | re.S),
]


def migration_files() -> list[Path]:
    return sorted(ROOT.glob("hub/**/migrations/versions/*.py"))


def violations(source: str, *, migration: bool) -> list[str]:
    patterns = REPLACE + (FORBIDDEN if migration and REVIEWED not in source else [])
    return [p.pattern for p in patterns if p.search(source)]


def test_there_are_migrations() -> None:
    assert migration_files()


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_migration_is_clean(path: Path) -> None:
    assert violations(path.read_text(), migration=True) == []


@pytest.mark.parametrize("path", migration_files(), ids=lambda p: p.name)
def test_no_downgrade_path(path: Path) -> None:
    source = path.read_text()
    assert "def downgrade" in source
    assert "raise NotImplementedError" in source.split("def downgrade", 1)[1]


def test_code_never_replaces_protected_rows() -> None:
    for path in ROOT.glob("hub/**/*.py"):
        assert violations(path.read_text(), migration=False) == [], path


def test_lint_catches_what_it_should() -> None:
    assert violations("op.execute('DELETE FROM audit')", migration=True)
    assert violations("with op.batch_alter_table('entries'):", migration=True)
    assert violations("INSERT OR REPLACE INTO entries VALUES (1)", migration=False)
    assert violations(
        "INSERT INTO links (a) VALUES (1) ON CONFLICT (a) DO UPDATE SET a=1", migration=False
    )
    assert not violations(f"{REVIEWED}\nDROP TRIGGER entries_no_update", migration=True)
    assert not violations("INSERT INTO rate_limits ON CONFLICT DO UPDATE", migration=False)
