// Bloc d'accueil de l'agenda (S11) : la semaine, les rappels ouverts, la liste de courses. Le
// pont Rappels/Calendrier absent (Mac en veille, accès retiré), le bloc le dit sans erreur.
import { date } from "./format.js";
import { store } from "./store.js";
import { esc, fill } from "./ui.js";

const PATH = "/agenda/overview";
const SHOWN = 5;

const when = (iso) => (iso && iso.length > 10 ? `${date(iso.slice(0, 10))} · ${iso.slice(11, 16)}` : iso ? date(iso) : "");

function rows(items, sub) {
  return items
    .slice(0, SHOWN)
    .map((x) => `<div class="row"><span class="row-main"><span class="row-title">${esc(x.title)}</span><span class="row-sub">${esc(sub(x))}</span></span></div>`)
    .join("");
}

export function render(box) {
  const o = store.use(PATH).data;
  if (!o) return;
  if (!o.available) {
    fill(box, `<section class="card" aria-labelledby="t-agenda"><h2 class="section-title" id="t-agenda">Agenda</h2><p class="note">Rappels et Calendrier ne répondent pas pour l'instant.</p></section>`);
    return;
  }
  const late = o.overdue ? ` · ${o.overdue} en retard` : "";
  fill(
    box,
    `<section class="card" aria-labelledby="t-agenda">
      <h2 class="section-title" id="t-agenda">Agenda</h2>
      ${o.events.length ? rows(o.events, (e) => when(e.start)) : '<p class="note">Rien au calendrier cette semaine.</p>'}
      ${o.reminders.length ? `<h3 class="row-sub">${o.reminders.length} rappel${o.reminders.length > 1 ? "s" : ""} ouvert${o.reminders.length > 1 ? "s" : ""}${late}</h3>${rows(o.reminders, (r) => when(r.due))}` : ""}
      ${o.shopping.length ? `<p class="note">Courses : ${o.shopping.map((s) => esc(s.title)).join(", ")}</p>` : ""}
    </section>`,
  );
}

