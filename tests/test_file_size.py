"""Conventions : un fichier de code tient en 400 lignes (Python et JavaScript de hub/, Python de
l'assistant : audit M12).

Les fichiers plus longs aujourd'hui sont listés avec leur taille : ils ne peuvent que rétrécir,
et sortent de la liste dès qu'ils repassent sous la barre. On n'y ajoute jamais un fichier : un
fichier qui grossit se découpe (chantier S0 du plan « Socle du hub »).
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOTS = ("hub", "assistant/domia_assistant", "assistant/bench")
LIMIT = 400

# chemin relatif au dépôt → taille maximale tolérée, en attendant le découpage (S5, S6)
TOO_LONG: dict[str, int] = {
    "hub/core/collectors.py": 460,
    "hub/collectors/exchanges/binance_history.py": 478,
    "hub/domains/finance/web/journal.js": 662,
    "hub/domains/finance/web/connections.js": 528,
    "hub/core/proposals.py": 636,
    "hub/collectors/market/flow.py": 592,
}


def _sizes() -> dict[str, int]:
    files = [
        p for root in ROOTS for p in (*(REPO / root).rglob("*.py"), *(REPO / root).rglob("*.js"))
    ]
    return {str(p.relative_to(REPO)): len(p.read_text().splitlines()) for p in files}


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
