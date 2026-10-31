// Accueil de la coquille (cœur), neutre : aucun domaine ne passe en tête. D'abord « À valider »
// (les propositions, cochées, et leur Face ID), « À faire » (ce qui se règle d'un geste) et
// « À savoir », tous domaines
// confondus, où chaque ligne porte le nom de son domaine et mène à l'écran où l'on agit ; puis
// le bloc de chaque domaine sous son titre, dans l'ordre des domaines.
// Le module d'accueil d'un domaine (manifeste `home`) exporte render(box) ; il peut exporter
// rows() : ses lignes { ic, c, mark, t, s, a, v, info }, ou null tant que ses données manquent.
import { card, pendingCount, pendingPath } from "./approvals.js";
import { store } from "./store.js";
import { esc, fill, ibox, ic } from "./ui.js";

const $ = (id) => document.getElementById(id);
const HOMES = []; // [domaine, module], dans l'ordre des domaines

export function add(domain, module) {
  HOMES.push([domain, module]);
}

// le conteneur des listes, puis un par domaine ; créés au premier rendu
function boxes() {
  const body = $("homeBody");
  if (!body.childElementCount) {
    for (const key of ["", ...HOMES.map(([d]) => d)]) {
      const b = Object.assign(document.createElement("div"), { className: "home-domain" });
      if (key) b.dataset.home = key;
      else b.dataset.lists = "";
      body.append(b);
    }
    body.insertAdjacentHTML("beforeend", '<div class="endspace"></div>');
  }
  return (key) => body.querySelector(key ? `:scope > [data-home="${CSS.escape(key)}"]` : ":scope > [data-lists]");
}

// null tant qu'un domaine attend ses données : les listes ne s'affichent pas à moitié
function rows() {
  const out = [];
  for (const [d, m] of HOMES) {
    if (!m.rows) continue;
    const r = m.rows();
    if (r == null) return null;
    out.push(...r.map((x) => ({ ...x, d })));
  }
  return out;
}

export function todoCount() {
  const all = rows();
  return pendingCount() + (all ? all.filter((x) => !x.info).length : 0);
}

const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const sub = (x) => (x.d ? `${capital(x.d)} · ${x.s}` : x.s);

const row = (x) => `<button class="trow press" type="button" data-a="${x.a}" ${x.v ? `data-v="${esc(x.v)}"` : ""}>
    ${x.mark || ibox(ic(x.ic), x.c)}
    <span class="row-main"><span class="row-title">${esc(x.t)}</span><span class="row-sub">${esc(sub(x))}</span></span>
    <span class="chev-r">${ic("chev")}</span></button>`;

function lists() {
  const all = rows();
  if (!all) return "";
  const acts = all.filter((x) => !x.info), infos = all.filter((x) => x.info);
  return `${card()}<section class="card" aria-labelledby="t-todo">
      <div class="section-head"><h2 class="section-title" id="t-todo">À faire</h2>${acts.length ? `<span class="pill info">${acts.length}</span>` : ""}</div>
      ${acts.length ? acts.map(row).join("") : `<div class="status good">${ic("check")}<span>Rien à faire, tout est à jour.</span></div>`}
    </section>
    ${infos.length ? `<section class="card" aria-labelledby="t-info"><h2 class="section-title" id="t-info">À savoir</h2>${infos.map(row).join("")}</section>` : ""}`;
}

export function render() {
  store.use(pendingPath);
  const at = boxes();
  for (const [d, m] of HOMES) m.render(at(d));
  fill(at(""), lists());
}
