"""Versions du hub (chantier S13) : une seule version SemVer, celle de pyproject.toml.

    python scripts/release.py prepare 0.12.0   # pyproject, uv.lock, section du CHANGELOG
    python scripts/release.py check [v0.12.0]  # version cohérente (et égale au tag donné)
    python scripts/release.py notes v0.12.0    # notes de version, tirées du CHANGELOG

`prepare` se lance sur une branche, avant la PR de version ; le tag se pose sur main après la
fusion (`make tag`), et c'est lui qui publie les images (.github/workflows/release.yml).
"""

import datetime as dt
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
UNRELEASED = "## [Non publié]"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
VERSION_LINE = re.compile(r'^version = "[^"]*"$', re.MULTILINE)


class ReleaseError(Exception):
    pass


def parse(version: str) -> tuple[int, int, int]:
    m = SEMVER.match(version.removeprefix("v"))
    if not m:
        raise ReleaseError(f"version SemVer attendue (X.Y.Z), reçu « {version} »")
    return int(m[1]), int(m[2]), int(m[3])


def current_version(pyproject: str) -> str:
    return str(tomllib.loads(pyproject)["project"]["version"])


def bump_pyproject(pyproject: str, version: str) -> str:
    out, n = VERSION_LINE.subn(f'version = "{version}"', pyproject, count=1)
    if n != 1:
        raise ReleaseError("ligne version introuvable dans pyproject.toml")
    return out


def _sections(changelog: str) -> list[tuple[str, str]]:
    """(titre, corps) de chaque section de niveau 2, dans l'ordre du fichier."""
    parts = re.split(r"^(## .*)$", changelog, flags=re.MULTILINE)
    return [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts), 2)]


def heading(version: str, day: dt.date) -> str:
    return f"## [{version}] · {day.isoformat()}"


def release_changelog(changelog: str, version: str, day: dt.date) -> str:
    """La section « Non publié » devient celle de la version ; une section vide la remplace."""
    if any(t.startswith(f"## [{version}]") for t, _ in _sections(changelog)):
        raise ReleaseError(f"le CHANGELOG a déjà une section {version}")
    body = dict(_sections(changelog)).get(UNRELEASED)
    if body is None:
        raise ReleaseError(f"section « {UNRELEASED} » introuvable")
    if not body.strip():
        raise ReleaseError("rien sous « Non publié » : aucune version à publier")
    return changelog.replace(UNRELEASED, f"{UNRELEASED}\n\n{heading(version, day)}", 1)


def notes(changelog: str, version: str) -> str:
    for title, body in _sections(changelog):
        if title.startswith(f"## [{version}]"):
            return body.strip() + "\n"
    raise ReleaseError(f"aucune section {version} dans le CHANGELOG")


def check(pyproject: str, package_version: str, tag: str | None, changelog: str) -> str:
    version = current_version(pyproject)
    parse(version)
    if package_version != version:
        raise ReleaseError(f"paquet installé {package_version} ≠ pyproject {version} (uv sync)")
    if tag is not None:
        if tag != f"v{version}":
            raise ReleaseError(f"tag {tag} ≠ version v{version} de pyproject.toml")
        notes(changelog, version)
    return version


def main(argv: list[str]) -> int:
    try:
        match argv:
            case ["prepare", version]:
                new = version.removeprefix("v")
                old = current_version(PYPROJECT.read_text())
                if parse(new) <= parse(old):
                    raise ReleaseError(f"{new} doit suivre la version actuelle {old}")
                log = release_changelog(
                    CHANGELOG.read_text(), new, dt.datetime.now().astimezone().date()
                )
                PYPROJECT.write_text(bump_pyproject(PYPROJECT.read_text(), new))
                CHANGELOG.write_text(log)
                subprocess.run(["uv", "lock"], cwd=ROOT, check=True)  # noqa: S607 (uv du PATH)
                print(f"{old} → {new} : pyproject.toml, uv.lock, CHANGELOG.md")
            case ["check", *rest] if len(rest) <= 1:
                from importlib.metadata import version as installed

                tag = rest[0] if rest else None
                v = check(
                    PYPROJECT.read_text(), installed("personal-hub"), tag, CHANGELOG.read_text()
                )
                print(f"version {v} cohérente" + (f", tag {tag}" if tag else ""))
            case ["notes", tag]:
                sys.stdout.write(notes(CHANGELOG.read_text(), tag.removeprefix("v")))
            case _:
                print(__doc__, file=sys.stderr)
                return 2
    except ReleaseError as exc:
        print(f"release : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
