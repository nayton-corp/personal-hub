// Patrimoine, liste Comptes / Actifs : chaque ligne dit sa valeur, son gain en francs et son
// rendement en pastille (▲ vert, ▼ rouge) sur la période choisie en haut ; un actif dit aussi sa
// quantité. Le tri se choisit dans un petit panneau : un critère, et pour chacun l'ordre
// (décroissant ou croissant). Les chiffres viennent de /finance/performance (agrégats par compte
// et par actif) : aucune écriture n'est lue ici.
import { SORTS, S, accLabel, accMark, range, remember, sum } from "./wstate.js";
import { SHEETS, amount, closeSheet, esc, ic, openSheet, qty } from "../../ui.js";
import { assetMark, facetColor, ringed } from "./meta.js";
import { rate, signedMoney, units } from "./perf.js";
import { DEBT_KIND, debtMark } from "./debts.js";
import { goodMark } from "./goods.js";
import { store } from "../../store.js";

const KIND = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };
// l'unité d'une crypto : son symbole, sans le préfixe interne « crypto: »
const unitOf = (f) => (f.unit === "parts" ? "parts" : (f.unit || "").replace(/^crypto:/i, "").toUpperCase());

function rowsOf(sel, M) {
  const groups = Object.groupBy(sel, (l) => (S.view === "acc" ? `a:${l.acc}` : `s:${l.asset}`));
  const perf = M.perf, net = M.net;
  const rows = Object.entries(groups).map(([key, ls]) => {
    const f = ls[0], value = sum(ls);
    const c = f.kind === "debt" ? net && net.by_account[f.acc] : perf && (S.view === "acc" ? perf.by_account[f.acc] : perf.by_asset[f.asset]);
    const gain = c && M.pts.length > 1 ? units(c.gain) : null, pct = c && M.pts.length > 1 ? rate(c.personal) : null;
    const base = { key, value, gain, pct };
    if (f.kind === "debt") return { ...base, title: f.name, sub: `${esc(f.inst)} · ${DEBT_KIND[f.debtKind] || "Dette"}`, mark: debtMark({ kind: f.debtKind }, ""), debt: true };
    if (f.kind === "good") return { ...base, gain: null, pct: null, title: f.name, sub: `Bien · ${esc(f.inst)}`, mark: goodMark({ kind: f.goodKind }, "") };
    if (S.view === "acc") return { ...base, title: f.accName, sub: `${esc(f.inst)} · ${KIND[f.kind] || ""}`, mark: accMark(ls, ""), cash: f.kind === "cash" };
    const nAcc = new Set(ls.map((l) => l.acc)).size, cash = f.asset.startsWith("ccy:");
    const q = ls.reduce((t, l) => t + Number(l.qty), 0);
    // la quantité d'abord ; le compte qui la tient se lit sur la page de l'actif
    const where = nAcc > 1 ? ` · ${nAcc} comptes` : cash ? ` · ${esc(accLabel(f))}` : "";
    return { ...base, title: f.name, sub: cash ? where.slice(3) : `<span class="money num">${qty(String(+q.toFixed(8)))}</span> ${esc(unitOf(f))}${where}`, mark: ringed(assetMark(f), facetColor("cat", f.cat)), cash };
  });
  // des liquidités sans intérêts n'ont ni gain ni rendement : elles se rangent après les autres
  for (const r of rows) if (r.cash && r.gain != null && Math.round(r.gain) === 0) Object.assign(r, { gain: null, pct: null });
  return rows;
}

// un critère et un ordre ; ce qui n'a pas de gain (un bien, un compte sans historique) va en bas
function order(rows) {
  const up = S.dir === "asc" ? 1 : -1;
  const key = { val: (r) => r.value, gain: (r) => r.gain, pct: (r) => r.pct }[S.sort];
  if (!key) return rows.sort((a, b) => up * a.title.localeCompare(b.title, "fr"));
  return rows.sort((a, b) => {
    const x = key(a), y = key(b);
    if (x == null || y == null) return (x == null) - (y == null) || a.title.localeCompare(b.title, "fr");
    return up * (x - y) || a.title.localeCompare(b.title, "fr");
  });
}

// la pastille : ▲ vert, ▼ rouge, gris à zéro ; la flèche dit le sens sans la couleur
export function pill(p) {
  if (p == null) return "";
  const z = Math.round(p * 1000) === 0, t = z ? "zero" : p > 0 ? "pos" : "neg";
  return `<span class="gpill ${t} num">${z ? "" : `<i aria-hidden="true">${p > 0 ? "▲" : "▼"}</i>`}<span class="sr">${z ? "" : p > 0 ? "hausse " : "baisse "}</span>${(Math.abs(p) * 100).toFixed(1).replace(".", ",")} %</span>`;
}

function delta(r) {
  if (r.gain == null) return "";
  if (r.debt) return `<span class="faint num">intérêts ${signedMoney(r.gain)}</span>`;
  const t = Math.round(r.gain) === 0 ? "zero" : r.gain > 0 ? "pos" : "neg";
  return `<span class="delta ${t} num">${signedMoney(r.gain)}</span>${pill(r.pct)}`;
}

const DIRS = { val: ["Plus grande d'abord", "Plus petite d'abord"], gain: ["Plus gros gain d'abord", "Plus grosse perte d'abord"],
  pct: ["Meilleur % d'abord", "Pire % d'abord"], az: ["Z → A", "A → Z"] };
const arrow = () => (S.dir === "asc" ? "↑" : "↓");
const dirWord = () => (S.sort === "az" ? (S.dir === "asc" ? "A → Z" : "Z → A") : S.dir === "asc" ? "croissant" : "décroissant");

// au-delà d'un an, le % d'une ligne est celui de toute la période, pas un taux annuel
const long = (M) => M.pts.length > 1 && Date.parse(M.pts[M.pts.length - 1].d) - Date.parse(M.pts[0].d) > 366 * 864e5;

export function listSection(sel, M) {
  const rows = order(rowsOf(sel, M)).filter((r) => Math.abs(r.value) >= 0.5 || S.view === "acc");
  const so = SORTS.find((s) => s.k === S.sort);
  return `<section class="section" aria-labelledby="t-detail"><div class="detail-head" id="detailHead">
      <div class="vtabs" role="group" aria-label="Comptes ou actifs">${[["acc", "Comptes"], ["asset", "Actifs"]].map(([k, l]) => `<button type="button" data-a="w-view" data-v="${k}" aria-pressed="${S.view === k}">${l}${S.view === k ? ` <b class="num">${rows.length}</b>` : ""}</button>`).join("")}</div>
      <button class="sort-btn" type="button" data-a="w-sort" aria-haspopup="dialog" aria-label="Trier par ${so.short}, ${dirWord()}. Changer le tri">${ic("sort")}${so.short} <b aria-hidden="true">${arrow()}</b></button></div>
    <h2 class="sr" id="t-detail">Comptes et actifs</h2>
    ${M.pts.length > 1 ? `<p class="list-cap">Gain et rendement ${esc(range().label)}${long(M) ? ", en tout (pas par an)" : ""}</p>` : ""}
    <div class="list">${rows.length ? rows.map((r) => `<button class="row row2 go-row" type="button" data-a="w-open" data-v="${esc(r.key)}">${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}</span><span class="row-sub">${r.sub}</span></span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta gline">${delta(r)}</span></span><span class="go">${ic("chev")}</span></button>`).join("")
      : '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>'}</div>
</section>`;
}

SHEETS.wsort = () => {
  const [down, up] = DIRS[S.sort];
  const opt = (s) => `<button class="row byrow" type="button" data-a="w-sort-by" data-v="${s.k}" aria-pressed="${S.sort === s.k}"><span class="row-main"><span class="row-title">${s.label}</span>${s.hint ? `<span class="row-sub">${s.hint}</span>` : ""}</span><span class="chk">${S.sort === s.k ? ic("check") : ""}</span></button>`;
  return {
    title: "Trier",
    body: `<div class="list">${SORTS.map(opt).join("")}</div>
      <h3 class="grp-title">Ordre</h3>
      <div class="seg" role="group" aria-label="Ordre">${[["desc", down], ["asc", up]].map(([k, l]) => `<button type="button" data-a="w-sort-dir" data-v="${k}" aria-pressed="${S.dir === k}">${l}</button>`).join("")}</div>`,
  };
};

const set = (patch) => { Object.assign(S, patch); remember(); store.notify(); };
export const actions = {
  "w-sort": () => openSheet("wsort"),
  // un nouveau critère part dans son ordre naturel : les plus grands d'abord, les noms de A à Z
  "w-sort-by": (v) => { closeSheet(); set({ sort: v, dir: v === S.sort ? S.dir : v === "az" ? "asc" : "desc" }); },
  "w-sort-dir": (v) => { set({ dir: v }); openSheet("wsort"); },
};
