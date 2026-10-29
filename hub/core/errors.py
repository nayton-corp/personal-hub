"""Erreurs `application/problem+json` (RFC 9457) avec un `type` stable."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"

# type stable -> (statut HTTP, titre)
PROBLEM_TYPES: dict[str, tuple[int, str]] = {
    "auth.missing": (401, "Authentification requise"),
    "auth.invalid": (401, "Jeton ou session invalide"),
    "auth.scope": (403, "Portée insuffisante"),
    "auth.bootstrap_invalid": (401, "Code d'amorçage invalide ou expiré"),
    "auth.passkey_invalid": (401, "Passkey refusée"),
    "auth.challenge_expired": (401, "Défi expiré"),
    "approval.signature_invalid": (401, "Signature de validation invalide"),
    "validation.params": (422, "Paramètres invalides"),
    "not_found": (404, "Introuvable"),
    "domain.unknown": (404, "Domaine inconnu"),
    "proposal.not_found": (404, "Proposition introuvable"),
    "proposal.expired": (410, "Proposition expirée"),
    "proposal.not_pending": (409, "Proposition déjà traitée"),
    "proposal.kind_unknown": (422, "Type de proposition inconnu"),
    "proposal.kind_not_allowed": (403, "Type de proposition interdit pour cette portée"),
    "proposal.not_reversible": (409, "Proposition sans inverse"),
    "conflict.state_changed": (409, "L'état a changé depuis l'aperçu"),
    "idempotency.key_mismatch": (409, "Clé d'idempotence déjà utilisée pour une autre demande"),
    "ledger.append_only": (500, "Tentative de modification du registre"),
    "import.duplicate_file": (409, "Fichier déjà importé"),
    "import.invalid_schema": (422, "Relevé illisible ou non conforme"),
    "import.unknown_account": (422, "Compte inconnu"),
    "import.before_opening": (409, "Relevé antérieur à l'ouverture du registre"),
    "import.archive_unavailable": (503, "Archivage chiffré indisponible"),
    "import.not_found": (404, "Import introuvable"),
    "import.not_applicable": (409, "Import sans relevé à valider"),
    "collector.unknown": (404, "Collecteur inconnu"),
    "collector.check_required": (409, "Un contrôle réussi est nécessaire avant la reprise"),
    "collector.not_enabled": (409, "Connexion suspendue ou désactivée : la réactiver d'abord"),
    "collector.link_unknown": (404, "Liaison inconnue ou expirée"),
    "connection.exists": (409, "Connexion déjà présente"),
    "rate_limited": (429, "Trop de tentatives"),
    "busy.retry": (503, "Base occupée, réessayer"),
    "internal": (500, "Erreur interne"),
}


class Problem(Exception):
    def __init__(
        self,
        type_: str,
        detail: str | None = None,
        *,
        status: int | None = None,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        if type_ not in PROBLEM_TYPES:
            raise ValueError(f"type d'erreur non déclaré : {type_}")
        default_status, title = PROBLEM_TYPES[type_]
        self.type = type_
        self.status = status or default_status
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra
        super().__init__(f"{type_}: {detail or title}")

    def body(self, instance: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "title": self.title, "status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if instance:
            out["instance"] = instance
        out.update(self.extra)
        return out


def problem_response(p: Problem, instance: str | None = None) -> JSONResponse:
    return JSONResponse(
        p.body(instance), status_code=p.status, media_type=PROBLEM_JSON, headers=p.headers
    )


_HTTP_TYPES = {401: "auth.missing", 403: "auth.scope", 404: "not_found", 405: "not_found"}


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(exc, request.url.path)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # on ne renvoie que l'emplacement et le type d'erreur, jamais la valeur reçue
        errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        return problem_response(Problem("validation.params", errors=errors), request.url.path)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        type_ = _HTTP_TYPES.get(exc.status_code, "internal")
        return problem_response(Problem(type_, status=exc.status_code), request.url.path)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        from hub.core.logging import get_logger

        type_ = "ledger.append_only" if "ledger.append_only" in str(exc) else "internal"
        get_logger("hub.api").error("api.unhandled", error=type(exc).__name__, type=type_)
        return problem_response(Problem(type_), request.url.path)
