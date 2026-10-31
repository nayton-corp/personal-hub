// L'agenda à l'accueil (S11, revu le 31/10) : pas de bloc à lui. Les rendez-vous et les rappels
// restent dans Rappels et Calendrier de l'iPhone ; seuls les rappels en retard remontent dans
// « À savoir », et la ligne ouvre l'assistant. Le pont absent (Mac en veille), rien ne s'affiche.
import { date } from "../../format.js";
import { store } from "../../store.js";
import { fill } from "../../ui.js";

const PATH = "/agenda/overview";
const SHOWN = 3;

const today = () => new Date().toLocaleDateString("sv-SE"); // AAAA-MM-JJ, à l'heure locale

export function rows() {
  const o = store.use(PATH).data;
  if (!o) return null;
  if (!o.available) return [];
  const late = o.reminders.filter((r) => r.due && r.due.slice(0, 10) < today());
  const out = late.slice(0, SHOWN).map((r) => ({ info: true, ic: "calendar", c: "var(--s3)", t: r.title, s: `Rappel en retard depuis le ${date(r.due.slice(0, 10))}`, a: "assistant-open" }));
  if (late.length > SHOWN) out.push({ info: true, ic: "calendar", c: "var(--s3)", t: `${late.length - SHOWN} autre${late.length - SHOWN > 1 ? "s" : ""} rappel${late.length - SHOWN > 1 ? "s" : ""} en retard`, s: "Dans Rappels", a: "assistant-open" });
  return out;
}

export function render(box) {
  fill(box, "");
}
