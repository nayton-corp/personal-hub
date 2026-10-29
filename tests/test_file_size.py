"""Conventions : un fichier de code tient en 400 lignes (Python et JavaScript de hub/).

Les fichiers plus longs aujourd'hui sont listés avec leur taille : ils ne peuvent que rétrécir,
et sortent de la liste dès qu'ils repassent sous la barre. On n'y ajoute jamais un fichier : un
fichier qui grossit se découpe (chantier S0 du plan « Socle du hub »).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "hub"
LIMIT = 400

# chemin relatif à hub/ → taille maximale tolérée, en attendant le découpage (S5, S6)
TOO_LONG: dict[str, int] = {
    "core/collectors.py": 460,
    "cli.py": 522,
    "collectors/exchanges/binance_history.py": 583,
    "web/budget.js": 600,
    "web/journal.js": 662,
    "web/connections.js": 730,
    "web/wealth.js": 827,
    "core/proposals.py": 832,
    "collectors/market/flow.py": 1047,
}


def _sizes() -> dict[str, int]:
    files = [*ROOT.rglob("*.py"), *ROOT.rglob("*.js")]
    return {str(p.relative_to(ROOT)): len(p.read_text().splitlines()) for p in files}


def test_new_files_stay_under_the_limit() -> None:
    over = {k: v for k, v in _sizes().items() if v > LIMIT and k not in TOO_LONG}
    assert over == {}, f"au-delà de {LIMIT} lignes : découper le fichier"


def test_listed_files_only_shrink() -> None:
    sizes = _sizes()
    grown = {k: (sizes[k], cap) for k, cap in TOO_LONG.items() if k in sizes and sizes[k] > cap}
    assert grown == {}, "un fichier de la liste a grossi : (taille, plafond)"


def test_list_holds_only_long_files() -> None:
    sizes = _sizes()
    stale = sorted(k for k in TOO_LONG if sizes.get(k, 0) <= LIMIT)
    assert stale == [], "repassé sous la barre ou disparu : le retirer de TOO_LONG"


def test_list_records_the_current_size() -> None:
    # un fichier qui a rétréci abaisse son plafond : la marge gagnée n'est pas reprise
    sizes = _sizes()
    slack = {k: (sizes[k], cap) for k, cap in TOO_LONG.items() if k in sizes and sizes[k] < cap}
    assert slack == {}, "abaisser le plafond à la taille actuelle : (taille, plafond)"
