// Bloc d'accueil des documents (S12) : les entretiens dus d'après les fiches d'objets, puis les
// derniers documents reçus. Rien à montrer, le bloc reste vide.
import { date } from "../../format.js";
import { store } from "../../store.js";
import { esc, fill } from "../../ui.js";

const PATH = "/documents/overview";

function row(title, sub) {
  return `<div class="row bare"><span class="row-main"><span class="row-title">${esc(title)}</span><span class="row-sub">${esc(sub)}</span></span></div>`;
}

export function render(box) {
  const o = store.use(PATH).data;
  if (!o || (!o.due.length && !o.recent.length)) return;
  const due = o.due.map((d) => row(`${d.name} : ${d.what}`, `dû depuis le ${date(d.since)}`)).join("");
  const recent = o.recent.map((d) => row(d.card || d.title, `${d.card ? `${d.title} · ` : ""}${date(d.at.slice(0, 10))}${d.household ? " · foyer" : ""}`)).join("");
  fill(
    box,
    `<section class="card" aria-labelledby="t-documents">
      <h2 class="section-title" id="t-documents">Documents</h2>
      ${due ? `<h3 class="row-sub">Entretiens à faire</h3>${due}` : ""}
      ${recent ? `<h3 class="row-sub">Derniers documents</h3>${recent}` : ""}
      <p class="note">${o.cards} fiche${o.cards > 1 ? "s" : ""} d'objets · ${o.documents} document${o.documents > 1 ? "s" : ""}</p>
    </section>`,
  );
}
