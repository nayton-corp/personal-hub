// Les documents à l'accueil (S12, revu le 31/10) : pas de bloc à eux, on les interroge par
// l'assistant. Seuls les entretiens dus d'après les fiches d'objets remontent dans « À savoir ».
import { date } from "../../format.js";
import { store } from "../../store.js";
import { fill } from "../../ui.js";

const PATH = "/documents/overview";

export function rows() {
  const o = store.use(PATH).data;
  if (!o) return null;
  return o.due.map((d) => ({ info: true, ic: "doc", c: "var(--s5)", t: `${d.name} : ${d.what}`, s: `Entretien dû depuis le ${date(d.since)}`, a: "assistant-open" }));
}

export function render(box) {
  fill(box, "");
}
