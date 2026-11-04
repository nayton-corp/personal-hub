"""Le cœur ne connaît aucun domaine (chantier S1) : ni source, ni banque, ni notion de finance ;
et rien, hors du pack pays, ne connaît un pays (audit M17).

Ce qu'un domaine apporte au cœur (connecteurs, packs pays, reprise des anciennes connexions)
passe par les points d'entrée du paquet, lus par `hub.core.registry.contributions`. Ce qu'une
instance sait de son pays (devise, fuseau, locale, banque, plafonds, consignes de l'IA, régions)
tient dans `hub/domains/finance/packs/<pays>` et dans les modules d'une source propre au pays.
Un mot d'une liste qui revient ailleurs (hors migrations, figées) fait échouer ce test : la
donnée va dans le domaine ou dans le pack, le code générique la reçoit.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

from hub.core import connectors, profile

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / "hub"
CORE = HUB / "core"
FINANCE = re.compile(
    r"\b(iban|camt|pillar\w*|3a|wallets?|portefeuilles?|crypto|bcf|viac|revolut|ibkr|binance"
    r"|kucoin|coinbase|swissborg|enable[ _]banking|aspsp\w*)\b",
    re.IGNORECASE,
)
# ce qui ne se dit que d'un pays, dans le code (hors commentaires et docstrings) : fuseau,
# locale, devise et pays en dur, mots de la banque et de ses libellés, régions, consignes
SWISS = re.compile(
    r"Europe/Zurich|fr-CH|hors Suisse|[\"']Suisse[\"']|[\"']CHF?[\"']|\bbcf\b|\btwint\b"
    r"|\bmaestro\b|\bbancomat\b|numero de carte|bancaire suisse",
    re.IGNORECASE,
)
# les modules génériques de la finance : tout sauf le pack, les sources (une source est d'une
# banque, d'un pays), les migrations et la reprise de l'ancien fichier de règles (figée)
FINANCE_DIR = HUB / "domains" / "finance"
SOURCE_PARTS = frozenset({"packs", "sources", "migrations", "legacy.py"})
# le front : la coquille et les écrans de la finance
FRONT = (HUB / "web", FINANCE_DIR / "web")


def _code_lines(path: Path) -> list[str]:
    """Les lignes du fichier, sans ses commentaires ni ses docstrings (Python), sans ses
    commentaires de ligne (JavaScript)."""
    text = path.read_text()
    lines = text.splitlines()
    if path.suffix != ".py":
        return [re.sub(r"(^|\s)//.*$", "", line) for line in lines]
    skip: set[int] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return ["" if n in skip else line for n, line in enumerate(lines, 1)]


def _hits(paths: list[Path], pattern: re.Pattern[str], base: Path) -> list[str]:
    return [
        f"{path.relative_to(base)}:{n}: {m.group(0)}"
        for path in paths
        for n, line in enumerate(_code_lines(path), 1)
        for m in [pattern.search(line)]
        if m
    ]


def test_core_names_no_finance_source() -> None:
    paths = [p for p in sorted(CORE.rglob("*.py")) if "migrations" not in p.parts]
    found = _hits(paths, FINANCE, CORE)
    assert found == [], "le cœur nomme un domaine : déplacer la donnée dans le domaine"


def test_core_and_generic_finance_name_no_country() -> None:
    paths = [p for p in sorted(CORE.rglob("*.py")) if "migrations" not in p.parts]
    paths += [p for p in sorted(HUB.glob("*.py"))]  # cli, lancement
    paths += [p for p in sorted((HUB / "brain").rglob("*.py"))]
    paths += [
        p
        for p in sorted(FINANCE_DIR.rglob("*.py"))
        if not SOURCE_PARTS & set(p.relative_to(FINANCE_DIR).parts)
    ]
    found = _hits(paths, SWISS, HUB)
    assert found == [], "un module générique nomme un pays : déplacer la donnée dans le pack"


def test_the_front_names_no_country() -> None:
    paths = [p for root in FRONT for p in sorted(root.rglob("*.js"))]
    found = _hits(paths, SWISS, HUB)
    assert found == [], "le front nomme un pays : la donnée vient du profil (`/profile`)"


def test_the_finance_contributes_through_entry_points() -> None:
    assert "enable_banking" in connectors.names()
    assert connectors.get("market") is not None
    assert "pillar3a" in profile.country_modules()["CH"]
    assert profile.country_defaults("CH") == {
        "locale": "fr-CH",
        "currency": "CHF",
        "timezone": "Europe/Zurich",
    }
    assert profile.country_defaults("BE") == {"locale": None, "currency": None, "timezone": None}
    assert "ai_context" in profile.country_public("CH")["finance"]
