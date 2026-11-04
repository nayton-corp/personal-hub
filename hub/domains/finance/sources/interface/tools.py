"""Outils de lecture des sources à parité avec ses routes (audit M11) : comptes vus dans des
relevés en attente. Le dépôt d'un relevé et le détail d'un import restent à l'app (session
passkey). Règles communes : registre/interface/tools.py."""

from __future__ import annotations

import re
from typing import Any, Protocol

from hub.core.domain import McpTool, ToolCaller
from hub.domains.finance.registre.app import catalog
from hub.domains.finance.registre.interface import http
from hub.domains.finance.registre.interface.tools import (
    AGGREGATES,
    NONE,
    NoArgs,
    ToolBox,
    tool,
)
from hub.domains.finance.sources.app import revolut_accounts
from hub.domains.finance.sources.app.importer import ImportService

_REVOLUT_REF = re.compile(r"revolut:([A-Z]{3})(:[a-z0-9-]+)?")


class Host(http.Host, Protocol):
    importer: ImportService


def pending_accounts(host: Host) -> list[dict[str, Any]]:
    """Comptes vus dans des relevés en attente mais pas encore créés : clé, devise, nombre
    d'écritures et période. Aucun montant. Partagé avec la route `/accounts/pending`."""
    out = []
    engine = host.engine()
    for ref, items in sorted(revolut_accounts.revolut_pending(host.importer).items()):
        with engine.connect() as conn:
            if catalog.account_by_ref(conn, ref) is not None:
                continue
        dates = [e.booking_date for _, st in items for e in st.entries]
        m = _REVOLUT_REF.fullmatch(ref)
        out.append(
            {
                "ref": ref,
                "institution": "Revolut",
                "kind": "cash",
                "currency": m.group(1) if m else None,
                "imports": len({i for i, _ in items}),
                "entries": sum(len(st.entries) for _, st in items),
                "from": min(dates, default=None),
                "to": max(dates, default=None),
                "can_open": any(st.derived_opening for _, st in items),
            }
        )
    return out


class SourcesTools(ToolBox):
    host: Host

    def pending(self, _a: NoArgs, caller: ToolCaller) -> dict[str, Any]:
        with self.engine.connect() as conn:
            return self._wrap(conn, {"pending_accounts": pending_accounts(self.host)})

    def tools(self, category: dict[str, Any]) -> list[McpTool]:
        return [
            tool(
                "finance_pending_accounts",
                "Comptes vus dans des relevés en attente (Revolut) mais pas encore créés : clé, "
                "devise, nombre d'écritures, période ; `finance_propose_create_account` les ouvre.",
                NONE,
                AGGREGATES,
                NoArgs,
                self.pending,
            )
        ]
