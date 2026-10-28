"""Packs de règles de départ (chantier « hub générique », G2).

Un pack est un fichier YAML versionné : les catégories qu'il utilise et des groupes de règles
(une catégorie, un sens, une priorité, des mots-clés). `base` porte les mots génériques et les
services internationaux, `ch` les commerces et prestataires suisses. Une base neuve reçoit
`base` et le pack de son pays ; une base existante garde ses règles et n'en reçoit qu'à la
demande (`hub finance rules packs install`).

Installer un pack ajoute les règles qui manquent (une règle de même forme déjà présente, quelle
que soit son origine, n'est pas doublée), garde désactivée une règle du pack que l'utilisateur a
coupée, et désactive les règles d'une version précédente du pack qui n'y sont plus. Les règles
personnelles s'exportent dans le même format (`rules export`) et se réinstallent comme un pack.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Connection, text

from hub.core.clock import now_iso
from hub.domains.finance import catalog, rules

FOLDER = Path(__file__).parent / "packs"
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
DIRECTIONS = ("any", "debit", "credit")


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Group:
    category: str
    direction: str
    priority: int
    keywords: tuple[str, ...]
    field: str = "search_text"


@dataclass(frozen=True)
class Pack:
    name: str
    version: int
    label: str
    description: str = ""
    country: str | None = None
    categories: tuple[catalog.Category, ...] = ()
    groups: tuple[Group, ...] = ()

    def specs(self) -> list[tuple[str, str, str, str, int]]:
        """Règles du pack : (champ, motif normalisé, sens, catégorie, priorité), sans doublon."""
        out: dict[tuple[str, str, str, str], int] = {}
        for g in self.groups:
            for kw in g.keywords:
                pattern = rules.normalize_pattern(g.field, kw)
                if g.field == "search_text" and kw and not pattern.strip():
                    continue
                out.setdefault((g.field, pattern, g.direction, g.category), g.priority)
        return [(*k, p) for k, p in out.items()]

    def rule_id(self, field: str, pattern: str, direction: str, category: str) -> str:
        return rules.rule_id(f"pack-{self.name}", field, pattern, direction, category)

    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "label": self.label,
            "description": self.description,
        }
        if self.country:
            doc["country"] = self.country
        doc["categories"] = [{"id": c.id, "name": c.name, "group": c.grp} for c in self.categories]
        doc["rules"] = [
            {
                "category": g.category,
                "direction": g.direction,
                "priority": g.priority,
                "keywords": list(g.keywords),
                **({} if g.field == "search_text" else {"field": g.field}),
            }
            for g in self.groups
        ]
        return doc


def parse(raw: str) -> Pack:
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PackError("YAML illisible") from exc
    if not isinstance(doc, dict):
        raise PackError("un pack est un dictionnaire")
    name = doc.get("name")
    version = doc.get("version")
    if not isinstance(name, str) or not _NAME.match(name):
        raise PackError("name : minuscules, chiffres et tirets")
    if not isinstance(version, int) or version < 1:
        raise PackError("version : entier positif")
    cats = []
    for c in doc.get("categories") or []:
        if not isinstance(c, dict) or c.get("group") not in catalog.GROUPS:
            raise PackError("categories : id, name et group (fixed, variable…) attendus")
        cats.append(catalog.Category(str(c["id"]), str(c["name"]), str(c["group"]), True))
    groups = []
    for i, g in enumerate(doc.get("rules") or []):
        kws = g.get("keywords") if isinstance(g, dict) else None
        if not isinstance(kws, list) or not all(isinstance(k, str) for k in kws):
            raise PackError(f"rules.{i} : liste de mots-clés attendue")
        direction = g.get("direction", "any")
        fld = g.get("field", "search_text")
        if direction not in DIRECTIONS or fld not in ("search_text", "counterparty_iban"):
            raise PackError(f"rules.{i} : sens ou champ inconnu")
        if not isinstance(g.get("priority", 100), int):
            raise PackError(f"rules.{i} : priorité entière attendue")
        groups.append(
            Group(str(g["category"]), direction, int(g.get("priority", 100)), tuple(kws), fld)
        )
    country = doc.get("country")
    return Pack(
        name,
        version,
        str(doc.get("label") or name),
        str(doc.get("description") or ""),
        str(country) if country else None,
        tuple(cats),
        tuple(groups),
    )


def available() -> dict[str, Pack]:
    """Packs livrés avec le hub, par nom."""
    return {p.name: p for p in (parse(f.read_text()) for f in sorted(FOLDER.glob("*.yaml")))}


def defaults_for(country: str) -> list[Pack]:
    """`base`, puis le pack du pays s'il existe."""
    found = available()
    return [found["base"], *(p for p in found.values() if p.country == country)]


def installed(conn: Connection) -> dict[str, int]:
    return {
        str(r[0]): int(r[1]) for r in conn.execute(text("SELECT name, version FROM rule_packs"))
    }


@dataclass
class Report:
    pack: str
    version: int
    added: int = 0
    kept: int = 0
    already: int = 0  # même règle déjà présente sous une autre origine
    disabled: int = 0  # règles d'une version précédente absentes de celle-ci
    categories_added: int = 0
    categorized: int = 0
    dry_run: bool = False
    missing: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return dict(self.__dict__)


def install(conn: Connection, pack: Pack, *, dry_run: bool = False, run: bool = True) -> Report:
    """Installe ou met à jour un pack dans la transaction de l'appelant."""
    report = Report(pack.name, pack.version, dry_run=dry_run)
    known = {c.id for c in catalog.list_categories(conn)}
    for c in pack.categories:
        if c.id not in known:
            report.categories_added += 1
            if not dry_run:
                conn.execute(
                    text("INSERT INTO categories (id, name, grp) VALUES (:i, :n, :g)"),
                    {"i": c.id, "n": c.name, "g": c.grp},
                )
            known.add(c.id)
    existing = rules.list_rules(conn)
    by_id = {r.id: r for r in existing}
    shapes = {(r.field, r.pattern, r.direction, r.category_id) for r in existing}
    wanted: set[str] = set()
    for fld, pattern, direction, category, priority in pack.specs():
        if category not in known:
            report.missing.append(category)
            continue
        rid = pack.rule_id(fld, pattern, direction, category)
        wanted.add(rid)
        if rid in by_id:
            report.kept += 1
            if not dry_run and by_id[rid].priority != priority:
                conn.execute(
                    text("UPDATE rules SET priority = :p WHERE id = :i"),
                    {"p": priority, "i": rid},
                )
        elif (fld, pattern, direction, category) in shapes:
            report.already += 1
        else:
            report.added += 1
            if not dry_run:
                rules.insert_rule(
                    conn,
                    id=rid,
                    field=fld,
                    pattern=pattern,
                    direction=direction,
                    category_id=category,
                    priority=priority,
                )
    prefix = f"pack-{pack.name}-"
    for r in existing:
        if r.id.startswith(prefix) and r.id not in wanted and r.active:
            report.disabled += 1
            if not dry_run:
                rules.set_active(conn, r.id, False)
    report.missing = sorted(set(report.missing))
    if dry_run:
        return report
    conn.execute(
        text(
            "INSERT INTO rule_packs (name, version, installed_at) VALUES (:n, :v, :at) "
            "ON CONFLICT (name) DO UPDATE SET version = excluded.version, "
            "installed_at = excluded.installed_at"
        ),
        {"n": pack.name, "v": pack.version, "at": now_iso()},
    )
    rules.bump_version(conn)
    if run:
        report.categorized = rules.run(conn)
    return report


def export(conn: Connection, name: str = "perso", *, origins: Iterable[str] = ()) -> Pack:
    """Les règles actives hors système (de départ, reprises, ajoutées ou d'un pack), au format
    d'un pack. `origins` restreint aux préfixes donnés (`user`, `legacy`…)."""
    if not _NAME.match(name):
        raise PackError("nom : minuscules, chiffres et tirets")
    wanted = tuple(f"{o}-" for o in origins)
    picked = [
        r
        for r in rules.list_rules(conn, active_only=True)
        if not r.id.startswith("system-")
        and r.field in ("search_text", "counterparty_iban")
        and (not wanted or r.id.startswith(wanted))
    ]
    grouped: dict[tuple[str, str, int, str], list[str]] = {}
    for r in picked:
        grouped.setdefault((r.category_id, r.direction, r.priority, r.field), []).append(r.pattern)
    cats = {c.id: c for c in catalog.list_categories(conn)}
    used = sorted({k[0] for k in grouped})
    return Pack(
        name,
        1,
        name,
        "Règles exportées d'un hub",
        None,
        tuple(cats[c] for c in used if c in cats),
        tuple(
            Group(cat, direction, prio, tuple(sorted(kws)), fld)
            for (cat, direction, prio, fld), kws in sorted(
                grouped.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])
            )
        ),
    )


def dump(pack: Pack) -> str:
    return yaml.safe_dump(pack.to_dict(), allow_unicode=True, sort_keys=False, width=100)
