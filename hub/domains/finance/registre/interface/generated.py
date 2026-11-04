"""Outils engendrés pour l'assistant (audit M11) : une proposition par type du Double Sas, à
partir de son modèle de paramètres. Les outils écrits à la main gardent leurs arguments plus
simples (catégorie en liste fermée, montant en unités) ; ceux-ci couvrent le reste."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from hub.core.domain import McpTool, ProposalKind, ToolCaller
from hub.core.errors import Problem
from hub.domains.finance.registre.interface.tools import PROPOSE, REASON_PROP


def kind_schema(kind: ProposalKind) -> dict[str, Any]:
    """Le schéma JSON des paramètres du type, plus `reason`."""
    schema = kind.params_model.model_json_schema()
    out: dict[str, Any] = {
        "type": "object",
        "properties": {**schema.get("properties", {}), "reason": REASON_PROP},
        "additionalProperties": False,
    }
    if schema.get("required"):
        out["required"] = list(schema["required"])
    if schema.get("$defs"):
        out["$defs"] = schema["$defs"]
    return out


def kind_tool(name: str, kind_name: str, kind: ProposalKind, description: str) -> McpTool:
    """`finance_propose_<type>` : valide les paramètres avec le modèle du type, puis crée la
    proposition (une carte à valider dans l'app ; rien n'est appliqué)."""

    def call(args: dict[str, Any], caller: ToolCaller) -> Any:
        params = dict(args)
        reason = params.pop("reason", None)
        try:
            parsed = kind.params_model.model_validate(params)
        except ValidationError as exc:
            errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
            raise Problem("validation.params", errors=errors) from None
        return caller.propose(kind_name, parsed.model_dump(mode="json"), reason)

    return McpTool(name, description, kind_schema(kind), PROPOSE, call)
