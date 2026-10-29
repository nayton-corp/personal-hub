"""Compte rendu d'un import : ce qu'est devenu chaque fichier et chaque relevé d'un lot
(identifiants et compteurs, jamais de contenu)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class FileOutcome:
    name: str
    import_id: str | None
    status: Literal["staged", "duplicate", "rejected", "ignored"]
    reason: str | None = None


@dataclass
class StatementOutcome:
    import_id: str
    index: int
    status: Literal["applied", "needs_review"]
    reasons: list[str]
    new: int = 0
    duplicates: int = 0


@dataclass
class BatchReport:
    files: list[FileOutcome] = field(default_factory=list)
    statements: list[StatementOutcome] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "duplicate_files": sum(f.status == "duplicate" for f in self.files),
            "rejected_files": sum(f.status == "rejected" for f in self.files),
            "ignored_files": sum(f.status == "ignored" for f in self.files),
            "statements": len(self.statements),
            "applied": sum(s.status == "applied" for s in self.statements),
            "needs_review": sum(s.status == "needs_review" for s in self.statements),
            "new_entries": sum(s.new for s in self.statements),
            "duplicate_entries": sum(s.duplicates for s in self.statements),
        }
