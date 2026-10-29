"""Versions du hub (S13) : une version SemVer, un tag égal, une section du CHANGELOG."""

import datetime as dt
import importlib.util
import tomllib
from pathlib import Path

import pytest

import hub

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
assert _spec
assert _spec.loader
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

PYPROJECT = '[project]\nname = "personal-hub"\nversion = "0.11.2"\n\n[tool.x]\nversion = "9"\n'
LOG = (
    "# Journal\n\n## [Non publié]\n\n### Nouveau\n\n- une chose\n\n"
    "## [0.11.2] · 2026-10-29\n\n- avant\n"
)
DAY = dt.date(2026, 10, 30)


def test_the_package_reports_the_pyproject_version() -> None:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert hub.__version__ == meta["project"]["version"]
    release.parse(hub.__version__)


def test_the_lock_follows_the_version() -> None:
    lock = (ROOT / "uv.lock").read_text()
    assert f'name = "personal-hub"\nversion = "{hub.__version__}"' in lock, "lancer uv lock"


def test_the_changelog_keeps_an_unreleased_section() -> None:
    assert release.UNRELEASED in (ROOT / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3.4", "01.2.3", "1.2.3-rc1", "latest"])
def test_only_plain_semver(bad: str) -> None:
    with pytest.raises(release.ReleaseError):
        release.parse(bad)


def test_bump_touches_only_the_project_version() -> None:
    out = release.bump_pyproject(PYPROJECT, "0.12.0")
    assert release.current_version(out) == "0.12.0"
    assert 'version = "9"' in out


def test_release_moves_unreleased_under_the_version() -> None:
    out = release.release_changelog(LOG, "0.12.0", DAY)
    assert out.index("## [Non publié]") < out.index("## [0.12.0] · 2026-10-30")
    assert release.notes(out, "0.12.0") == "### Nouveau\n\n- une chose\n"
    assert release.notes(out, "0.11.2") == "- avant\n"
    # la nouvelle section « Non publié » est vide : publier deux fois de suite est refusé
    with pytest.raises(release.ReleaseError, match="rien sous"):
        release.release_changelog(out, "0.12.1", DAY)


def test_release_refuses_a_known_version() -> None:
    with pytest.raises(release.ReleaseError, match="déjà"):
        release.release_changelog(LOG, "0.11.2", DAY)


def test_check_compares_package_tag_and_changelog() -> None:
    assert release.check(PYPROJECT, "0.11.2", "v0.11.2", LOG) == "0.11.2"
    with pytest.raises(release.ReleaseError, match="uv sync"):
        release.check(PYPROJECT, "0.1.0", None, LOG)
    with pytest.raises(release.ReleaseError, match="tag"):
        release.check(PYPROJECT, "0.11.2", "v0.12.0", LOG)
    with pytest.raises(release.ReleaseError, match="aucune section"):
        release.check(PYPROJECT, "0.11.2", "v0.11.2", "## [Non publié]\n")
