"""Formes de sortie des routes des sources (audit M10) ; règles : registre/interface/schemas.py."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from hub.domains.finance.registre.interface.schemas import Out


class PendingAccountOut(Out):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ref: str
    institution: str
    kind: str
    currency: str | None
    imports: int
    entries: int
    from_: str | None = Field(default=None, alias="from")
    to: str | None
    can_open: bool


class PendingAccountsOut(Out):
    items: list[PendingAccountOut]


class UploadItemOut(Out):
    import_id: str | None
    status: str


class CountersOut(Out):
    files: int
    statements: int
    new_entries: int
    duplicate_entries: int
    duplicate_files: int
    rejected_files: int
    ignored_files: int
    applied: int
    needs_review: int


class UploadOut(Out):
    items: list[UploadItemOut]
    counters: CountersOut


class StatementOut(Out):
    index: int
    account_id: str | None
    opbd_date: str | None
    clbd_date: str | None
    status: str
    reasons: list[str]
    new: int
    duplicates: int


class ImportDetailOut(Out):
    id: str
    source: str
    file_name: str
    received_at: str
    status: str
    stats: dict[str, Any]
    statements: list[StatementOut]
    proposal_id: str | None
