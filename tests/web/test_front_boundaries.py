"""Les frontières du front, comme import-linter pour le Python : la coquille (`hub/web`) ne
connaît aucun domaine, et un domaine n'importe que la coquille et ses propres modules, servis
depuis son dossier `web/` sous /d/<domaine>/."""

from __future__ import annotations

import re
from pathlib import Path

from hub.domains.agenda.domain import MANIFEST as AGENDA
from hub.domains.documents.domain import MANIFEST as DOCUMENTS
from hub.domains.finance.manifest import MANIFEST as FINANCE

HUB = Path(__file__).resolve().parents[2] / "hub"
SHELL = HUB / "web"
DOMAINS = {"finance": FINANCE, "agenda": AGENDA, "documents": DOCUMENTS}
IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*["']([^"']+\.js)["']""")


def _imports(f: Path) -> list[str]:
    return IMPORT.findall(f.read_text())


def test_the_shell_imports_only_itself() -> None:
    bad = {
        f.name: spec
        for f in SHELL.glob("*.js")
        for spec in _imports(f)
        if not (spec.startswith("./") and "/" not in spec[2:] and (SHELL / spec[2:]).is_file())
    }
    assert bad == {}


def test_the_shell_names_no_domain() -> None:
    files = [*SHELL.glob("*.js"), SHELL / "index.html", SHELL / "styles.css"]
    found = {
        (f.name, name)
        for f in files
        for name in DOMAINS
        if re.search(rf"/(api/)?{name}\b|\b{name}\.(js|css)\b", f.read_text())
    }
    assert found == set()


def test_a_domain_imports_only_the_shell_and_itself() -> None:
    bad = []
    for name in DOMAINS:
        web = HUB / "domains" / name / "web"
        for f in web.glob("*.js"):
            for spec in _imports(f):
                own = spec.startswith("./") and (web / spec[2:]).is_file()
                shell = spec.startswith("../../") and (SHELL / spec[6:]).is_file()
                if not (own or shell) or "/" in spec.removeprefix("../../").removeprefix("./"):
                    bad.append((name, f.name, spec))
    assert bad == []


def test_every_declared_module_is_in_its_domain_folder() -> None:
    for name, manifest in DOMAINS.items():
        app = manifest.app
        assert app.web == HUB / "domains" / name / "web", name
        declared = [t.module for t in app.tabs] + [s.module for s in app.settings]
        declared += [m for m in (app.cards, app.home, app.module) if m]
        assert [m for m in declared if not (app.web / m).is_file()] == [], name
