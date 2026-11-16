// Patrimoine, liste Comptes / Actifs : chaque ligne dit sa valeur, son gain depuis l'achat en
// francs et en pastille (▲ vert, ▼ rouge), comme les apps de placement : la période choisie en haut
// ne change que la courbe et la carte du haut. Sans prix de revient (prévoyance, compte bancaire,
// achat absent du registre), le gain depuis l'ouverture : valeur − versements nets, sur toute
// l'histoire (/finance/performance sans date de début). Une dette dit ses intérêts de la période. Un
// actif dit aussi sa quantité. Le tri se choisit dans un petit panneau : un critère, et pour chacun l'ordre
// (décroissant ou croissant). Une ligne se masque (l'œil, ou d'elle-même à zéro) sans quitter
// les calculs. Les prix de revient viennent de /finance/holdings (par position, et commun à tous
// les comptes pour une crypto), les intérêts d'une dette de /finance/performance : aucune écriture
// n'est lue ici.
import { SORTS, S, accLabel, accMark, lines, perfPath, remember, sum, unitOf } from "./wstate.js";
import { SHEETS, amount, closeSheet, esc, ic, openSheet, qty } from "../../ui.js";
import { assetMark, facetColor, ringed } from "./meta.js";
import { signedMoney, units } from "./perf.js";
import { assetSince, buyGain } from "./wcrypto.js";
import { perfSel, sinceStart } from "./wcurve.js";
import { DEBT_KIND, debtMark } from "./debts.js";
import { goodMark } from "./goods.js";
import { store } from "../../store.js";

const KIND = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };

function rowsOf(sel, M) {
  const groups = Object.groupBy(sel, (l) => (S.view === "acc" ? `a:${l.acc}` : `s:${l.asset}`));
  const net = M.net, all = lines() || sel;
  // toute l'histoire, par compte et par actif : le gain depuis l'ouverture quand le prix de revient manque
  const ever = store.use(perfPath(null, null, "month", perfSel(sel, all))).data;
  const rows = Object.entries(groups).map(([key, ls]) => {
    const f = ls[0], value = sum(ls);
    const debt = f.kind === "debt" && net && M.pts.length > 1 ? net.by_account[f.acc] : null;
    // une crypto tenue dans la liste par tous ses comptes : le prix de revient commun, celui de sa page
    const every = S.view === "asset" && f.kind === "crypto" && ls.length === (lines() || []).filter((l) => l.asset === f.asset).length;
    const pool = every ? assetSince(f.isin) : null;
    const e = ever && (S.view === "acc" ? ever.by_account[f.acc] : ever.by_asset[f.asset]);
    const bought = f.kind === "debt" || f.kind === "good" ? null
      : buyGain(ls, pool) || (e ? sinceStart(units(e.gain), units(e.start), units(e.net_flows)) : null);
    const gain = debt ? units(debt.gain) : bought ? bought.gain : null, pct = bought ? bought.pct : null;
    const base = { key, value, gain, pct };
    if (f.kind === "debt") return { ...base, title: f.name, sub: `${esc(f.inst)} · ${DEBT_KIND[f.debtKind] || "Dette"}`, mark: debtMark({ kind: f.debtKind }, ""), debt: true };
    if (f.kind === "good") return { ...base, gain: null, pct: null, title: f.name, sub: `Bien · ${esc(f.inst)}`, mark: goodMark({ kind: f.goodKind }, "") };
    if (S.view === "acc") return { ...base, title: f.accName, sub: `${esc(f.inst)} · ${KIND[f.kind] || ""}`, mark: accMark(ls, ""), cash: f.kind === "cash" };
    const held = ls.filter((l) => Math.abs(l.value) >= 0.5), nAcc = new Set((held.length ? held : ls).map((l) => l.acc)).size, cash = f.asset.startsWith("ccy:");
    const q = ls.reduce((t, l) => t + Number(l.qty), 0);
    // la quantité d'abord ; le compte qui la tient se lit sur la page de l'actif
    const where = nAcc > 1 ? ` · ${nAcc} comptes` : cash ? ` · ${esc(accLabel(f))}` : "";
    const amt = `<span class="money num">${qty(String(+q.toFixed(8)))}</span> ${esc(unitOf(f))}`;
    return { ...base, title: f.name, sub: cash ? where.slice(3) : amt + where, mark: ringed(assetMark(f), facetColor("cat", f.cat)), cash };
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
  const head = z ? "" : `<i aria-hidden="true">${p > 0 ? "▲" : "▼"}</i><span class="sr">${p > 0 ? "hausse " : "baisse "}</span>`;
  return `<span class="gpill ${t} num">${head}${(Math.abs(p) * 100).toFixed(1).replace(".", ",")} %</span>`;
}

function delta(r) {
  if (r.gain == null || (Math.abs(r.value) < 0.5 && Math.round(r.gain) === 0)) return "";
  if (r.debt) return `<span class="faint num">intérêts ${signedMoney(r.gain)}</span>`;
  const t = Math.round(r.gain) === 0 ? "zero" : r.gain > 0 ? "pos" : "neg";
  return `<span class="delta ${t} num">${signedMoney(r.gain)}</span>${pill(r.pct)}`;
}

const DIRS = { val: ["Plus grande d'abord", "Plus petite d'abord"], gain: ["Plus gros gain d'abord", "Plus grosse perte d'abord"],
  pct: ["Meilleur % d'abord", "Pire % d'abord"], az: ["Z → A", "A → Z"] };
const arrow = () => (S.dir === "asc" ? "↑" : "↓");
const dirWord = () => (S.sort === "az" ? (S.dir === "asc" ? "A → Z" : "Z → A") : S.dir === "asc" ? "croissant" : "décroissant");

let LAST = { all: [] }; // lignes du dernier rendu, pour le panneau « Lignes masquées »

// une ligne masquée (à la main, ou à zéro) quitte la liste mais reste dans les totaux, la courbe
// et le gain : seul l'affichage change ; elle ne se voit plus du tout, l'œil du panneau la rend
const zero = (r) => Math.abs(r.value) < 0.5;
const muted = (r) => S.muted.has(r.key) || (S.zero && zero(r));
const rowHTML = (r) => `<button class="row row2 go-row" type="button" data-a="w-open" data-v="${esc(r.key)}">${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}</span><span class="row-sub">${r.sub}</span></span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta gline">${delta(r)}</span></span><span class="go">${ic("chev")}</span></button>`;

const pl = (n) => (n > 1 ? "s" : "");

export function listSection(sel, M) {
  const all = order(rowsOf(sel, M));
  LAST = { all };
  const rows = all.filter((r) => !muted(r)), hid = all.length - rows.length;
  const so = SORTS.find((s) => s.k === S.sort);
  const n = all.length - hid, word = S.view === "acc" ? "compte" : "actif";
  return `<section class="section" aria-labelledby="t-detail"><div class="detail-head" id="detailHead">
      <div class="vtabs" role="group" aria-label="Comptes ou actifs">${[["acc", "Comptes"], ["asset", "Actifs"]].map(([k, l]) =>
        `<button type="button" data-a="w-view" data-v="${k}" aria-pressed="${S.view === k}">${l}${S.view === k ? ` <b class="num">${n}</b>` : ""}</button>`).join("")}</div>
      <button class="sort-btn" type="button" data-a="w-sort" aria-haspopup="dialog"
        aria-label="Trier par ${so.short}, ${dirWord()}. Changer le tri et l'affichage">${ic("sort")}${so.short} <b aria-hidden="true">${arrow()}</b></button></div>
    <h2 class="sr" id="t-detail">Comptes et actifs</h2>
    <p class="list-cap">Gain depuis l'achat, ou depuis l'ouverture sans prix d'achat</p>
    <div class="list">${rows.length ? rows.map(rowHTML).join("")
      : hid ? "" : '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>'}</div>
    ${hid ? `<button class="list-foot" type="button" data-a="w-mutes">${ic("eyeoff")}${hid} ${word}${pl(hid)} masqué${pl(hid)},
      toujours compté${pl(hid)} · <b>Gérer</b></button>` : ""}
</section>`;
}

SHEETS.wsort = () => {
  const [down, up] = DIRS[S.sort];
  const opt = (s) => `<button class="row byrow" type="button" data-a="w-sort-by" data-v="${s.k}" aria-pressed="${S.sort === s.k}">
    <span class="row-main"><span class="row-title">${s.label}</span>${s.hint ? `<span class="row-sub">${s.hint}</span>` : ""}</span>
    <span class="chk">${S.sort === s.k ? ic("check") : ""}</span></button>`;
  const dir = ([k, l]) => `<button type="button" data-a="w-sort-dir" data-v="${k}" aria-pressed="${S.dir === k}">${l}</button>`;
  const hand = S.muted.size ? `${S.muted.size} masqué${pl(S.muted.size)} à la main` : "aucun pour l'instant";
  return {
    title: "Trier et afficher",
    body: `<div class="list">${SORTS.map(opt).join("")}</div>
      <h3 class="grp-title">Ordre</h3>
      <div class="seg" role="group" aria-label="Ordre">${[["desc", down], ["asc", up]].map(dir).join("")}</div>
      <h3 class="grp-title">Lignes masquées</h3>
      <p class="hint">Elles quittent la liste mais restent dans le total, la courbe et le gain.</p>
      <div class="setrow"><span id="zero-lbl">Masquer les lignes à zéro<small>Comptes vidés, actifs vendus</small></span>
        <button class="switch" type="button" role="switch" aria-checked="${S.zero}" aria-labelledby="zero-lbl" data-a="w-zero"></button></div>
      <button class="setrow linkrow" type="button" data-a="w-mutes"><span>Choisir les ${S.view === "acc" ? "comptes" : "actifs"} à masquer<small>${hand}</small></span>${ic("chev")}</button>`,
  };
};

// chaque ligne de la vue, avec son œil ; une ligne à zéro déjà masquée le dit
SHEETS.wmute = () => ({
  title: S.view === "acc" ? "Comptes affichés" : "Actifs affichés",
  body: `<p class="hint">Touche l'œil pour masquer une ligne de la liste. Elle reste dans le total, la courbe, la répartition et le gain.</p>
    <div class="list">${LAST.all.map((r) => {
      const auto = S.zero && zero(r) && !S.muted.has(r.key), off = muted(r);
      return `<div class="setrow mrow${off ? " off" : ""}">${r.mark}<span>${esc(r.title)}<small>${auto ? "masqué car à zéro" : off ? "masqué" : amount(r.value)}</small></span>
        <button class="eyebtn" type="button" data-a="w-mute" data-v="${esc(r.key)}" aria-pressed="${off}"
          aria-label="${off ? "Afficher" : "Masquer"} ${esc(r.title)}"${auto ? " disabled" : ""}>${ic(off ? "eyeoff" : "eye")}</button></div>`;
    }).join("")}</div>`,
});

const set = (patch) => { Object.assign(S, patch); remember(); store.notify(); };
export const actions = {
  "w-sort": () => openSheet("wsort"),
  // un nouveau critère part dans son ordre naturel : les plus grands d'abord, les noms de A à Z
  "w-sort-by": (v) => { closeSheet(); set({ sort: v, dir: v === S.sort ? S.dir : v === "az" ? "asc" : "desc" }); },
  "w-sort-dir": (v) => { set({ dir: v }); openSheet("wsort"); },
  "w-zero": () => { set({ zero: !S.zero }); openSheet("wsort"); },
  "w-mutes": () => openSheet("wmute"),
  "w-mute": (v) => { if (S.muted.has(v)) S.muted.delete(v); else S.muted.add(v); set({}); openSheet("wmute"); },
};
