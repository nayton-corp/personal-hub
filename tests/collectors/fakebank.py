"""Fausse banque et faux VIAC en HTML local : reproduisent la forme des écrans que les bots
parcourent (frames, formulaire d'export, liste de documents), sans aucune donnée réelle."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.factories.camt import Stmt, Tx, camt053
from tests.factories.viac import deposit, fake_pdf

PAGE = "<!doctype html><meta charset=utf-8><title>{title}</title><body>{body}</body>"

BCF_LOGIN = """
<form id=f><input type=text name=contract><input type=password name=pw><button>Valider</button></form>
<p id=msg></p>
<script>
f.onsubmit = (e) => {{
  e.preventDefault();
  fetch('/api/login', {{method: 'POST', body: f.contract.value + '|' + f.pw.value}})
    .then((r) => r.text()).then((t) => {{
      if (t === 'refused') {{ msg.textContent = 'Mot de passe incorrect.'; return; }}
      msg.textContent = 'Confirmez la connexion sur votre téléphone.';
      if (t === 'push') setTimeout(() => {{ location.href = '/home'; }}, {push_ms});
    }});
}};
</script>"""

BCF_HOME = """<nav><a href=/logout>Déconnexion</a></nav><iframe id=main src=/frame width=900 height=700></iframe>"""
BCF_FRAME = """<a href="/statement">Toutes les écritures</a>"""
BCF_STATEMENT = """
<button id=exp>Exporter (PDF et autres)</button>
<form id=form hidden onsubmit="return false">
  <label><input type=radio name=format value=PDF checked>PDF</label>
  <label><input type=radio name=format value=CAMT053>camt.053</label>
  <label><input type=radio name=dataSource value=oneAccount checked>un compte</label>
  <label><input type=radio name=dataSource value=allAccounts>tous</label>
  <label><input type=checkbox name=alreadyFetchedBookings>déjà exportés</label>
  <input id=findatepick_0_text type=text>
  <button type=button class=primary id=dl>Télécharger</button>
  <p id=out></p>
</form>
<script>
exp.onclick = () => {{ form.hidden = false; }};
const d = document.getElementById('findatepick_0_text');
d.addEventListener('change', () => {{
  if (/^\\d{{2}}\\/\\d{{2}}\\/\\d{{4}}$/.test(d.value)) d.setAttribute('date-value', d.value);
}});
dl.onclick = () => {{
  const q = new URLSearchParams({{
    format: form.format.value, all: form.dataSource.value,
    fetched: form.alreadyFetchedBookings.checked ? '1' : '0', since: d.getAttribute('date-value') || ''}});
  fetch('/api/export?' + q).then((r) => r.text()).then((t) => {{
    if (t === 'nothing') {{ out.textContent = 'Rien à exporter.'; return; }}
    const a = document.createElement('a'); a.href = '/download?' + q; a.download = 'export.xml'; a.click();
  }});
}};
</script>"""

VIAC_LOGIN = """
<form id=f><input type=email name=user><input type=password name=pw><button>Connexion</button></form>
<form id=o hidden><input name=otpcode inputmode=numeric autocomplete=one-time-code><button>OK</button></form>
<script>
f.onsubmit = (e) => {{ e.preventDefault();
  if ({direct}) {{ fetch('/api/viac-login', {{method: 'POST'}}).then(() => {{ location.href = '/viac-home'; }}); return; }}
  f.hidden = true; o.hidden = false; }};
o.onsubmit = (e) => {{ e.preventDefault();
  fetch('/api/otp', {{method: 'POST', body: o.otpcode.value}}).then((r) => r.text()).then((t) => {{
    if (t === 'ok') location.href = '/documents'; }}); }};
</script>"""

VIAC_DOCS = """
<table><tbody>{rows}</tbody></table>
<button class="mat-mdc-paginator-navigation-next" disabled>›</button>
<button class="spec-generate-reporting">Créer un rapport</button>
<div class=cdk-overlay-container></div>
<script>
document.querySelector('.spec-generate-reporting').onclick = () => {{
  document.querySelector('.cdk-overlay-container').innerHTML =
    '<div role=dialog><label>Date de référence <input id=rd></label><button id=create>Créer</button></div>';
  document.getElementById('create').onclick = () => {{
    const a = document.createElement('a');
    a.href = '/report?d=' + encodeURIComponent(document.getElementById('rd').value);
    a.download = 'rapport.pdf'; a.click();
  }};
}};
</script>"""

VIAC_ROW = (
    "<tr class=mat-mdc-row><td><span class=cell-content>{name}</span></td>"
    "<td><span class=cell-content>Portefeuille   1</span></td>"
    "<td><span class=cell-content>{on}</span></td><td><span class=cell-content>PDF</span></td>"
    "<td><a class=spec-get-single-document href='/doc/{i}' download>↓</a></td></tr>"
)


def camt_file(on: date) -> bytes:
    return camt053(Stmt(Decimal("100.00"), on, [Tx("12.50", True, on)]))


@dataclass
class Bank:
    """État de la fausse banque, modifiable par les tests."""

    login: str = "push"  # push | refused | never
    push_ms: int = 300
    export: str = "file"  # file | nothing | bad
    viac_session: bool = True
    otp: str = "123456"
    viac_2fa: bool = True  # False : connexion sans code, arrivée sur l'accueil
    documents: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("Versement", "03.10.2026"),
            ("Attestation fiscale", "15.01.2026"),
            ("Dividende", "02.09.2026"),
        ]
    )
    calls: list[str] = field(default_factory=list)
    exports: list[dict[str, str]] = field(default_factory=list)


def _handler(bank: Bank) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def _send(
            self, body: bytes, ctype: str = "text/html; charset=utf-8", **headers: str
        ) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            for k, v in headers.items():
                self.send_header(k.replace("_", "-"), v)
            self.end_headers()
            self.wfile.write(body)

        def _page(self, title: str, body: str) -> None:
            self._send(PAGE.format(title=title, body=body).encode())

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length).decode()
            path = urlsplit(self.path).path
            bank.calls.append(path)
            if path == "/api/login":
                self._send(
                    ("refused" if bank.login == "refused" else bank.login).encode(), "text/plain"
                )
            elif path == "/api/viac-login":
                bank.viac_session = True
                self._send(b"ok", "text/plain")
            elif path == "/api/otp":
                if data == bank.otp:
                    bank.viac_session = True
                self._send(b"ok" if data == bank.otp else b"no", "text/plain")

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(parts.query).items()}
            path = parts.path
            bank.calls.append(path)
            if path == "/login":
                self._page("BCF", BCF_LOGIN.format(push_ms=bank.push_ms))
            elif path == "/home":
                self._page("BCF", BCF_HOME)
            elif path == "/frame":
                self._page("cadre", BCF_FRAME)
            elif path == "/statement":
                self._page("Mouvements", BCF_STATEMENT.format())
            elif path == "/api/export":
                bank.exports.append(q)
                self._send(b"nothing" if bank.export == "nothing" else b"file", "text/plain")
            elif path == "/download":
                body = (
                    b"<html>pas un camt</html>"
                    if bank.export == "bad"
                    else camt_file(date(2026, 10, 20))
                )
                self._send(
                    body, "application/xml", Content_Disposition="attachment; filename=export.xml"
                )
            elif path == "/logout":
                self._page("BCF", "<p>Au revoir</p>")
            elif path == "/documents":
                if not bank.viac_session:
                    direct = "false" if bank.viac_2fa else "true"
                    self._page("VIAC", VIAC_LOGIN.format(direct=direct))
                    return
                rows = "".join(
                    VIAC_ROW.format(name=n, on=on, i=i) for i, (n, on) in enumerate(bank.documents)
                )
                self._page("VIAC", VIAC_DOCS.format(rows=rows))
            elif path == "/viac-home":
                self._page("VIAC", "<h1>Accueil</h1><p>Vos portefeuilles</p>")
            elif path.startswith("/doc/"):
                i = int(path.rsplit("/", 1)[1])
                _name, _on = bank.documents[i]
                body = fake_pdf(deposit(date(2026, 10, 3), f"{100 + i}.00")) + b"\n%%EOF\n"
                self._send(
                    body, "application/pdf", Content_Disposition=f"attachment; filename=d{i}.pdf"
                )
            elif path == "/report":
                body = fake_pdf("Rapport " + q.get("d", "")) + b"\n%%EOF\n"
                self._send(
                    body, "application/pdf", Content_Disposition="attachment; filename=r.pdf"
                )
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


@contextmanager
def serve(bank: Bank) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(bank))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
