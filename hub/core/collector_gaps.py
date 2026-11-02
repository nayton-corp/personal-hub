"""Ce qu'un run réussi n'a pas pu lire : un collecteur qui finit « ok » en sautant une partie de
sa source le dit dans son détail (`partial <portée>:<raison> …`). Ce run n'est pas complet : l'app
le montre avec son action (politique de calcul, docs/finance-politique.md), au lieu de le
compter comme les autres.

Le cœur ne connaît que la forme : une portée (étape, sous-étapes séparées par des points) et une
raison (`needs_key`, `pruned`, `unsupported`, un résultat de run, `skipped=<n>`). Les mots pour
le dire viennent du domaine qui a déclaré la connexion.
"""

from __future__ import annotations

from typing import Any

PREFIX = "partial "


def parse(detail: str | None) -> list[dict[str, str]]:
    """[{scope, reason}] d'un détail `partial …` ; vide pour un run complet."""
    if not detail or not detail.startswith(PREFIX):
        return []
    out = []
    for token in detail[len(PREFIX) :].split():
        scope, _sep, reason = token.rpartition(":")
        if not scope:
            scope, reason = token, "unknown"
        out.append({"scope": scope, "reason": reason})
    return out


def of_run(last_run: dict[str, Any] | None) -> list[dict[str, str]]:
    """Les manques du dernier run, s'il a réussi ; un run en échec se dit déjà par son résultat."""
    if not last_run or last_run.get("outcome") not in ("ok", "nothing_new"):
        return []
    return parse(last_run.get("detail"))
