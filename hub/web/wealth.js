// Patrimoine : une sélection (filtres par catégorie, disponibilité, objectif, institution) pilote
// tout l'écran : total et courbe, répartition, performance, puis le détail par compte ou par
// actif, chacun dépliable et relié à l'autre. Les lignes viennent de /finance/accounts et
// /finance/holdings ; la courbe, le gain et le rendement, de /finance/performance pour les lignes
// choisies (les versements n'y sont pas du gain). Les dettes (/finance/debts) sont des lignes
// négatives de catégorie « Dettes » : le total est net.
import { DEBT_KIND, debtDetail, debtMark } from "./debts.js";
import { go, reveal } from "./shell.js";
import { linkTo } from "./journal.js";
import { MOIS, MOIS_L, base } from "./format.js";
import { gainSpan, perfSection, perfSummary, rate, ratePct, signedMoney, tone, units } from "./perf.js";
import { CCY_NAME, FACET, FACETS, assetMark, facetColor, facetIc, facetMark, facetName, lookMark, setInstitutions } from "./meta.js";
import { store } from "./store.js";
import {
  SHEETS, amount, announce, closeSheet, cv, esc, fill, ic, money, n0, n2, openSheet, pctOnly, pf, pref, qty, setPref, sgn, share, skel, toast,
} from "./ui.js";

const $ = (id) => document.getElementById(id);
const paths = { accounts: "/finance/accounts", holdings: "/finance/holdings", history: "/finance/networth/history", fresh: "/finance/freshness", debts: "/finance/debts" };
const KIND_LABEL = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto", debt: "Dette" };
// le pas de la courbe suit la période : un point par jour jusqu'à 3 mois, par semaine jusqu'à un
// an, par mois au-delà
const PERIODS = [
  { k: "1M", label: "sur 1 mois", days: 30, step: "day" },
  { k: "3M", label: "sur 3 mois", days: 91, step: "day" },
  { k: "YTD", label: "depuis le 1er janvier", step: "week" },
  { k: "1A", label: "sur 1 an", days: 365, step: "week" },
  { k: "5A", label: "sur 5 ans", days: 1826, step: "month" },
  { k: "Max", label: "depuis le début", step: "month" },
];
const BY = ["cat", "liq", "goal", "inst"];
// répartition : tes choix (filtrent l'écran) ou le contenu des fonds (/finance/lookthrough)
const LOOK = [["region", "Région"], ["sector", "Secteur"], ["currency", "Devise"]];
const LOOK_KEYS = LOOK.map(([k]) => k);
const SORTS = [{ k: "val", label: "Valeur" }, { k: "chg", label: "Gain" }, { k: "az", label: "Nom" }];
const MODES = [["val", "Valeur"], ["gain", "Gain"], ["rend", "Rendement"]];
const TABS = [["rend", "Rendement"], ["risk", "Risque"]];
const W = 340, H = 170, L = 2, R = 2, T = 10, BOT = 22;

const saved = pref("wealth", {});
const S = {
  filters: { cat: new Set(), liq: new Set(), goal: new Set(), inst: new Set() },
  by: BY.includes(saved.by) || LOOK_KEYS.includes(saved.by) ? saved.by : "cat",
  period: PERIODS.some((p) => p.k === saved.period) ? saved.period : "1A",
  mode: saved.mode === "perf" ? "rend" : MODES.some(([k]) => k === saved.mode) ? saved.mode : "val",
  tab: TABS.some(([k]) => k === saved.tab) ? saved.tab : "rend",
  view: saved.view === "asset" ? "asset" : "acc",
  sort: SORTS.some((s) => s.k === saved.sort) ? saved.sort : "val",
  gross: saved.gross === true, // Brut : les dettes sortent du total, de la courbe et de la répartition
  open: new Set(),
  bridge: new Set(), // lignes dont le pont « D'où vient la valeur » est ouvert
  scrub: null,
};
const FOLD = { evo: false, alloc: false, perf: true, ...pref("fold", {}) };
let pts = []; // points de la courbe affichée

function remember() {
  const { by, period, mode, view, sort, tab, gross } = S;
  setPref("wealth", { ...pref("wealth", {}), by, period, mode, view, sort, tab, gross });
}

// --- lignes : un actif dans un compte ---------------------------------------------------------

function lastValues() {
  const h = store.data(paths.history);
  const last = h && h.items.length ? h.items[h.items.length - 1] : null;
  return last ? last.by_account : null;
}

let cache = { key: null, lines: [] };
function lines() {
  const acc = store.data(paths.accounts), hold = store.data(paths.holdings), byAcc = lastValues(), owed = store.data(paths.debts);
  if (!acc || !hold || !byAcc || !owed) return null;
  const key = [acc, hold, byAcc, owed];
  if (cache.key && cache.key.every((x, i) => x === key[i])) return cache.lines;
  setInstitutions(acc.items.map((a) => a.institution));
  const out = [];
  for (const a of acc.items) {
    if (a.hidden) continue;
    const total = byAcc[a.id] ? byAcc[a.id].minor / 100 : 0;
    const own = hold.items.filter((p) => p.account_id === a.id);
    const meta = { acc: a.id, accName: a.name, inst: a.institution, liq: a.availability, goal: a.goal, kind: a.kind };
    let held = 0;
    for (const p of own) {
      const v = p.value.minor / 100;
      held += v;
      const crypto = p.kind === "crypto";
      out.push({ ...meta, asset: `isin:${p.isin}`, name: p.name, symbol: crypto ? p.isin : null, cat: a.category || (crypto ? "crypto" : "funds"), qty: p.quantity, unit: crypto ? p.isin : "parts", value: v, price: p.price, priceCcy: p.price_currency, priceDate: p.price_date });
    }
    const rest = total - held;
    if (!own.length || Math.abs(rest) >= 1) {
      // sans positions : le solde, dans la devise du compte ; avec : le reste, déjà converti
      const ccy = own.length ? base() : a.balance.currency;
      const q = own.length ? rest : a.balance.minor / 100;
      out.push({ ...meta, asset: `ccy:${ccy}`, name: CCY_NAME[ccy] || ccy, symbol: ccy, cat: a.category || (a.kind === "crypto" && !own.length ? "crypto" : "cash"), qty: q, unit: ccy, value: own.length ? rest : total });
    }
  }
  // une dette : sa valeur (négative) du dernier point ; ni disponibilité ni objectif
  for (const d of owed.items) {
    const v = byAcc[d.key];
    if (!v || !v.minor) continue;
    out.push({ acc: d.key, debt: d.id, accName: d.name, inst: d.lender, liq: null, goal: null, kind: "debt", debtKind: d.kind, asset: `debt:${d.id}`, name: d.name, symbol: null, cat: "debt", qty: v.minor / 100, unit: base(), value: v.minor / 100 });
  }
  cache = { key, lines: out };
  return out;
}

const activeCount = () => FACETS.reduce((n, f) => n + S.filters[f.key].size, 0);
function match(l, except) {
  for (const f of FACETS) {
    if (f.key === except) continue;
    const s = S.filters[f.key];
    if (s.size && !s.has(l[f.key])) return false;
  }
  return true;
}
const sum = (ls) => ls.reduce((t, l) => t + l.value, 0);

// identifiant d'une ligne pour /finance/performance : « compte|ISIN », « compte|cash », « debt:… »
export const lineId = (l) => (l.kind === "debt" ? l.asset : l.asset.startsWith("isin:") ? `${l.acc}|${l.asset.slice(5)}` : `${l.acc}|cash`);


// --- période et points ------------------------------------------------------------------------

const per = () => PERIODS.find((p) => p.k === S.period);
const iso = (d) => d.toISOString().slice(0, 10);
const day = (s) => new Date(`${s}T00:00:00Z`);

function startDate(h) {
  const asOf = day(h.as_of || h.items[h.items.length - 1].on_date);
  const p = per();
  if (p.k === "YTD") return `${asOf.getUTCFullYear() - 1}-12-31`;
  if (p.k === "Max") return h.items[0].on_date;
  const d = new Date(asOf);
  d.setUTCDate(d.getUTCDate() - p.days);
  return iso(d);
}

export const perfPath = (from, step, ids) =>
  `/finance/performance?${from ? `from=${from}&` : ""}step=${step}${ids ? ids.map((i) => `&line=${encodeURIComponent(i)}`).join("") : ""}`;

// lignes demandées : aucune sans filtre (le serveur prend celles de l'app), sinon la sélection ;
// « compte|cash » porte aussi les revenus et frais d'un compte à positions (sans valeur)
function selIds(sel, all = false) {
  if (all) return null;
  const ids = new Set(sel.map(lineId));
  for (const l of sel) if (l.kind !== "debt") ids.add(`${l.acc}|cash`);
  return [...ids].sort();
}

// Deux lectures quand la sélection a une dette : la courbe en net (dettes comprises), et la
// performance des seuls avoirs. Comme chez un gestionnaire, le rendement et le risque ne
// portent que sur ce que tu possèdes : les intérêts restent sur la ligne de la dette.
function seriesSource(h, sel) {
  if (!sel.length) return { items: [], status: "ok", data: null, assets: null };
  const from = startDate(h), step = per().step;
  const owned = sel.filter((l) => l.kind !== "debt");
  const plain = !activeCount() && !S.gross;
  const e = store.use(perfPath(from, step, selIds(sel, plain)));
  const a = owned.length < sel.length && owned.length ? store.use(perfPath(from, step, selIds(owned))) : e;
  return { items: e.data ? e.data.items : null, status: e.status === "ok" ? a.status : e.status, error: e.error || a.error, data: e.data, assets: a.data, hasDebt: owned.length < sel.length };
}

const fmtDate = (s, long) => {
  const d = day(s);
  if (long) return `${d.getUTCDate()} ${MOIS_L[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  const span = pts.length > 1 ? (day(pts[pts.length - 1].d) - day(pts[0].d)) / 864e5 : 0;
  return span >= 180 ? `${MOIS[d.getUTCMonth()]} ${d.getUTCFullYear()}` : `${d.getUTCDate()} ${MOIS[d.getUTCMonth()]}`;
};

// --- rendu ------------------------------------------------------------------------------------

export function init() {
  fill($("patBody"), `
    <div class="hero" id="evo">
      <div id="hero"></div>
      <div class="sec-body" id="evoBody">
        <svg class="chart" id="chart" viewBox="0 0 ${W} ${H}" tabindex="0" role="img" aria-label="Courbe d'évolution. Flèches gauche et droite pour lire une date."></svg>
        <div class="chart-legend" id="legend"></div>
        <div class="estimate" id="estimate" hidden></div>
        <div class="chips-row" id="periods" role="group" aria-label="Période"></div>
        <div class="seg small" id="modeSeg" role="group" aria-label="Mesure"></div>
      </div>
      <div id="heroFoot"></div>
    </div>
    <section class="section" id="alloc" aria-labelledby="t-alloc">
      <div class="section-head"><button class="fold-btn" type="button" data-a="w-fold" data-v="alloc" aria-controls="alloc-body"><h2 class="section-title" id="t-alloc">Répartition</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
      <button class="sec-sum" id="allocSum" type="button" data-a="w-fold" data-v="alloc" aria-label="Déplier la répartition"></button>
      <div class="sec-body" id="alloc-body">
        <div id="bySeg"></div>
        <svg class="chart tm" id="tm" viewBox="0 0 340 200" aria-hidden="true"></svg>
        <p class="hint" id="tmHint"></p>
        <div class="alloc-list" id="allocList"></div>
      </div>
    </section>
    <section class="section" id="perf" aria-labelledby="t-perf">
      <div class="section-head"><button class="fold-btn" type="button" data-a="w-fold" data-v="perf" aria-controls="perf-body"><h2 class="section-title" id="t-perf">Performance</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button><span class="head-extra sec-note" id="perfNote"></span></div>
      <button class="sec-sum" id="perfSum" type="button" data-a="w-fold" data-v="perf" aria-label="Déplier la performance"></button>
      <div class="sec-body" id="perf-body">
        <div class="scroll-x"><div class="seg small" id="tabSeg" role="group" aria-label="Thème"></div></div>
        <div id="tabBody"></div>
      </div>
    </section>
    <section class="section" id="detail" aria-labelledby="t-detail">
      <div class="detail-head" id="detailHead">
        <div class="seg" id="viewSeg" role="group" aria-label="Niveau de détail"></div>
        <div class="detail-meta"><span id="listCount"></span><button class="sort-btn" id="sortBtn" type="button" data-a="w-sort"></button></div>
      </div>
      <h2 class="sr" id="t-detail">Détail</h2>
      <div class="list" id="list"></div>
    </section>
    <div class="endspace"></div>`);
  const svg = $("chart");
  const scrubAt = (e) => {
    if (pts.length < 2) return;
    const r = svg.getBoundingClientRect(), x = ((e.clientX - r.left) / r.width) * W;
    setScrub(Math.round(Math.max(0, Math.min(1, (x - L) / (W - L - R))) * (pts.length - 1)));
  };
  svg.addEventListener("pointerdown", scrubAt);
  svg.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse" || e.buttons) scrubAt(e); });
  for (const ev of ["pointerleave", "pointerup", "pointercancel"]) {
    svg.addEventListener(ev, () => { if (S.scrub != null && document.activeElement !== svg) setScrub(null); });
  }
  svg.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Escape", "Home", "End"].includes(e.key) || pts.length < 2) return;
    e.preventDefault();
    if (e.key === "Escape") return setScrub(null);
    const cur = S.scrub == null ? pts.length - 1 : S.scrub;
    const next = e.key === "Home" ? 0 : e.key === "End" ? pts.length - 1 : cur + (e.key === "ArrowLeft" ? -1 : 1);
    setScrub(Math.max(0, Math.min(pts.length - 1, next)));
    announce($("hero").innerText.replace(/\s+/g, " "));
  });
  svg.addEventListener("blur", () => { if (S.scrub != null) setScrub(null); });
  window.addEventListener("scroll", () => {
    if (store.params.tab === "patrimoine") $("pat-top").classList.toggle("compact", window.scrollY > 110);
  }, { passive: true });
}

function setScrub(i) {
  if (i === S.scrub) return;
  S.scrub = i;
  drawChart();
}

let current = null; // { all, sel, items, h, src, perf }

export function render() {
  const ae = store.use(paths.accounts), he = store.use(paths.holdings), hi = store.use(paths.history), de = store.use(paths.debts);
  store.use(paths.fresh);
  const err = [ae, he, hi, de].find((e) => e.status === "error");
  const all = lines();
  renderFilterbar();
  if (err || !all) {
    fill($("hero"), err ? `<div class="err-box" role="alert">Impossible de charger le patrimoine : ${esc(err.error.message)}</div>` : skel());
    for (const id of ["heroFoot", "list", "allocList", "tm", "allocSum", "perfSum", "tabBody", "legend"]) fill($(id), "");
    $("chart").replaceChildren();
    return;
  }
  const h = hi.data;
  const sel = all.filter((l) => match(l) && !(S.gross && l.kind === "debt"));
  const src = h.items.length ? seriesSource(h, sel) : { items: [], status: "ok", data: null, assets: null };
  current = { all, sel, items: src.items, h, src, perf: src.assets || src.data, net: src.data };
  for (const k of ["evo", "alloc", "perf"]) {
    $(k).classList.toggle("folded", FOLD[k]);
    const b = $(k).querySelector(".fold-btn");
    if (b) b.setAttribute("aria-expanded", String(!FOLD[k]));
  }
  drawControls();
  drawChart();
  drawFoot(all, sel);
  drawAlloc(sel);
  drawPerf();
  drawList(all, sel);
  requestAnimationFrame(() => $("detailHead").style.setProperty("--topbar-h", `${$("pat-top").offsetHeight}px`));
}

function renderFilterbar() {
  const n = activeCount();
  let h = `<button class="fbtn${n ? " active" : ""}" type="button" data-a="filters" aria-haspopup="dialog">${ic("filter")}Filtres${n ? `<span class="count" aria-label="${n} actifs">${n}</span>` : ""}</button>`;
  if (!n) h += '<span class="chip-hint">Tout le patrimoine</span>';
  for (const f of FACETS) for (const v of S.filters[f.key]) {
    h += `<button class="chip" type="button" data-a="w-opt" data-v="${f.key}|${esc(v)}" aria-label="Retirer le filtre ${esc(facetName(f.key, v))}">${esc(facetName(f.key, v))}${ic("close")}</button>`;
  }
  if (n > 1) h += '<button class="clear-link" type="button" data-a="w-clear">Tout effacer</button>';
  fill($("filterbar"), h);
}

function drawControls() {
  fill($("modeSeg"), MODES.map(([k, l]) => `<button type="button" data-a="w-mode" data-v="${k}" aria-pressed="${S.mode === k}">${l}</button>`).join(""));
  fill($("periods"), PERIODS.map((p) => `<button class="pchip" type="button" data-a="w-period" data-v="${p.k}" aria-pressed="${S.period === p.k}" aria-label="Période ${p.label}">${p.k}</button>`).join(""));
}

function heroTop(scrubbed) {
  const { sel } = current;
  const n = activeCount();
  const scrub = scrubbed != null;
  const first = pts[0], p = scrub ? pts[scrubbed] : pts[pts.length - 1];
  const v = scrub ? p.v : sum(sel);
  const since = scrub ? `depuis le ${fmtDate(first.d, true)}` : per().label;
  // le grand chiffre suit la mesure : la valeur, le gain en francs ou le rendement en %
  const mode = pts.length > 1 ? S.mode : "val";
  const label = scrub ? `<span class="scrub-date">${fmtDate(p.d, true)}</span>`
    : `<span>${mode === "val" ? (n ? "Sélection filtrée" : S.gross ? "Patrimoine brut, sans les dettes" : "Patrimoine net") : mode === "gain" ? `Gain ${since}, versements exclus` : `Rendement ${since}, pondéré dans le temps`}</span>`;
  const big = mode === "val" ? `<span class="money">${n0(v)}</span><small>${base()}</small>`
    : mode === "gain" ? `<span class="${tone(p.g)}">${signedMoney(p.g)}</span><small>${base()}</small>`
    : `<span class="${tone(p.r)}">${ratePct(p.r)}</span>`;
  const sub = pts.length < 2 ? "" : mode === "val"
    ? `<div class="hero-delta">${gainSpan(p.g, p.r)}<span class="period-link">de gain ${since}</span></div><div class="hero-sub num">${n ? "Apports nets" : "Épargne"} ${signedMoney(p.f)} · variation totale ${signedMoney(p.v - first.v)}</div>`
    : mode === "gain" ? `<div class="hero-sub">Ce que tes placements ont rapporté ou coûté en ${base()}, sans tes versements. Il dépend de combien était investi.</div>`
    : '<div class="hero-sub">Le rendement de tes placements, calculé comme VIAC : un versement ne le change pas. Comparable à un indice.</div>';
  fill($("hero"), `<div class="hero-label">${label}</div><div class="hero-amount num">${big}</div>${sub}`);
  fill($("miniTotal"), `${n ? "Sélection · " : ""}${money(sum(sel))} ${base()}`);
}

function drawChart() {
  if (!current) return;
  const { sel, items, src, perf } = current;
  const svg = $("chart");
  const est = $("estimate");
  // valeur et versements en net ; gain, rendement et recul sur les seuls avoirs
  const own = src.assets && src.assets !== src.data ? new Map(src.assets.items.map((it) => [it.on_date, it])) : null;
  pts = (items || []).map((it) => {
    const o = own ? own.get(it.on_date) || it : it;
    return { d: it.on_date, v: units(it.value), f: units(it.net_flows), g: units(o.gain), r: rate(o.twr), dd: rate(o.drawdown), ok: it.complete, a: own ? units(o.value) : null };
  });
  const gaps = perf && perf.summary && !perf.summary.complete;
  est.hidden = !gaps;
  est.textContent = gaps ? "Des cours ou des changes manquent sur une partie de la période : une ligne sans cours entre dans le gain à son premier cours comme un versement." : "";
  if (S.scrub != null && S.scrub >= pts.length) S.scrub = null;
  heroTop(S.scrub);
  fill($("legend"), "");
  if (src && src.status === "error") return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Courbe indisponible : ${esc(src.error.message)}</text>`);
  if (!items) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Chargement…</text>`);
  if (!sel.length) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Aucune donnée pour cette sélection</text>`);
  if (pts.length < 2) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Courbe en construction : un point par fin de mois</text>`);
  const v0 = pts[0].v;
  const ys = pts.map((p) => (S.mode === "val" ? p.v : S.mode === "gain" ? p.g : p.r ?? 0));
  const dep = S.mode === "val" ? pts.map((p) => v0 + p.f) : null; // départ + versements nets
  const av = S.mode === "val" ? pts.filter((p) => p.a != null).map((p) => p.a) : [];
  let mn = Math.min(...ys, ...(dep || [])), mx = Math.max(...ys, ...(dep || []), ...av);
  if (S.mode !== "val") { mn = Math.min(mn, 0); mx = Math.max(mx, 0); }
  const pad = (mx - mn) * 0.08 || Math.abs(mx) * 0.05 || 1;
  mn -= pad; mx += pad;
  const X = (i) => L + (W - L - R) * (i / (pts.length - 1)), Y = (v) => T + (H - T - BOT) * (1 - (v - mn) / (mx - mn));
  const path = (vs) => vs.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const line = path(ys);
  let under = "";
  const banded = dep && pts.some((p) => p.a != null && p.a - p.v >= 1);
  if (dep) {
    // entre la valeur et les versements : vert quand le marché a ajouté, rouge quand il a retiré ;
    // avec une dette, la bande de la dette prend la place (le gain reste écrit au-dessus)
    for (let i = 1; i < ys.length && !banded; i++) {
      const up = ys[i] + ys[i - 1] >= dep[i] + dep[i - 1];
      under += `<path class="zone ${up ? "pos" : "neg"}" d="M${X(i - 1).toFixed(1)},${Y(ys[i - 1]).toFixed(1)}L${X(i).toFixed(1)},${Y(ys[i]).toFixed(1)}L${X(i).toFixed(1)},${Y(dep[i]).toFixed(1)}L${X(i - 1).toFixed(1)},${Y(dep[i - 1]).toFixed(1)}Z"/>`;
    }
    under += `<path class="dep" d="${path(dep)}"/>`;
    // la dette : bande rouge entre les avoirs (trait fin) et le net
    if (banded) {
      const av = pts.map((p) => (p.a == null ? p.v : p.a));
      under += `<path class="debtband" d="${path(av)}${ys.map((v, i) => `L${X(ys.length - 1 - i).toFixed(1)},${Y(ys[ys.length - 1 - i]).toFixed(1)}`).join("")}Z"/><path class="assets" d="${path(av)}"/>`;
    }
  } else {
    const z = Y(0).toFixed(1);
    under = `<line class="zero" x1="${L}" x2="${W - R}" y1="${z}" y2="${z}"/><path class="area" d="${line}L${X(ys.length - 1).toFixed(1)},${z}L${X(0).toFixed(1)},${z}Z"/>`;
  }
  const si = S.scrub == null ? ys.length - 1 : S.scrub;
  const cx = X(si), cy = Y(ys[si]);
  fill(svg, `<defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop class="g0" offset="0"/><stop class="g1" offset="1"/></linearGradient></defs>
    ${under}<path class="line" d="${line}"/>
    <text x="${L}" y="${H - 6}">${fmtDate(pts[0].d)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${fmtDate(pts[pts.length - 1].d)}</text>
    ${S.scrub != null ? `<line class="cursor" x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${T}" y2="${H - BOT}"/>` : ""}
    <circle class="dot" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5"/>`);
  fill($("legend"), S.mode === "val"
    ? `<span><i></i>${current.src.hasDebt ? "Net" : "Valeur"}</span><span><i class="dash"></i>Départ + ${activeCount() ? "apports nets" : "épargne"}</span>${current.src.hasDebt ? '<span><i class="thin"></i>Avoirs</span><span>Bande rouge : tes dettes</span>' : "<span>Écart vert : gain, rouge : perte</span>"}`
    : S.mode === "gain" ? `<span><i></i>Gain cumulé ${per().label}, versements exclus</span>`
    : '<span><i></i>Rendement pondéré dans le temps : les versements n\'y comptent pas</span>');
}

function drawFoot(all, sel) {
  const n = activeCount();
  const total = sum(sel), whole = sum(all);
  const nacc = new Set(sel.map((l) => l.acc)).size;
  const owed = sum(all.filter((l) => l.kind === "debt"));
  const anyDebt = all.some((l) => l.kind === "debt");
  fill($("heroFoot"), `
    ${anyDebt ? `<div class="netgross"><div class="seg small" role="group" aria-label="Dettes dans le total"><button type="button" data-a="w-gross" data-v="net" aria-pressed="${!S.gross}">Net</button><button type="button" data-a="w-gross" data-v="gross" aria-pressed="${S.gross}">Brut</button></div>
      <span class="hint">${S.gross ? `Sans les dettes (${amount(owed)})` : `Avoirs ${amount(whole - owed)} · dettes ${amount(owed)}`}</span></div>` : ""}
    ${n && whole > 0 ? `<div class="share"><div class="sharebar"><i data-css="width:${Math.max(0, Math.min(100, (total / whole) * 100)).toFixed(1)}%"></i></div>${share(total / whole)} de ton patrimoine (${amount(whole)})</div>` : ""}
    <div class="hero-foot"><div class="fresh">${nacc} compte${nacc > 1 ? "s" : ""}</div>
    <button class="graph-toggle" type="button" data-a="w-fold" data-v="evo" aria-expanded="${!FOLD.evo}" aria-controls="evoBody">${FOLD.evo ? "Afficher la courbe" : "Masquer la courbe"}<svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>`);
}

// Répartition en blocs : la surface d'un bloc est sa part. « Tes choix » découpe la sélection et
// filtre l'écran au toucher ; « Contenu des fonds » regarde à l'intérieur des fonds (tous les
// placements, plus les liquidités pour la devise) et montre les actifs qui y contribuent.
function allocRows(sel) {
  if (!LOOK_KEYS.includes(S.by)) {
    const g = {};
    for (const l of sel) if (l[S.by] != null) g[l[S.by]] = (g[l[S.by]] || 0) + l.value;
    return { rows: Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ k, v, name: facetName(S.by, k), c: facetColor(S.by, k), mark: facetMark(S.by, k) })) };
  }
  const e = store.use(`/finance/lookthrough?dimension=${S.by}`);
  if (e.status === "error") return { error: e.error.message };
  if (!e.data) return { loading: true };
  const items = e.data.items.map((x) => ({ k: x.bucket, v: units(x.value), assets: x.assets || [] }));
  if (S.by === "currency") {
    // les liquidités, par devise du compte, s'ajoutent aux fonds
    for (const l of current.all) {
      if (!l.asset.startsWith("ccy:") || l.kind === "debt" || l.value <= 0) continue;
      const it = items.find((x) => x.k === l.unit) || items[items.push({ k: l.unit, v: 0, assets: [] }) - 1];
      it.v += l.value;
    }
  }
  const rows = items.filter((x) => x.v >= 0.5).sort((a, b) => b.v - a.v);
  return { rows: rows.map((x, i) => ({ ...x, name: x.k, c: cv(i), mark: lookMark(S.by, x.k, cv(i)) })), fund: true };
}

// découpage en deux moitiés de poids égal, dans le sens le plus long, jusqu'à un bloc par valeur
function layout(rows, x, y, w, h, out = []) {
  if (!rows.length) return out;
  if (rows.length === 1) { out.push({ r: rows[0], x, y, w, h }); return out; }
  const tot = rows.reduce((t, r) => t + r.v, 0);
  let acc = 0, k = 0;
  while (k < rows.length - 1 && acc + rows[k].v <= tot / 2) acc += rows[k++].v;
  if (!k) { acc = rows[0].v; k = 1; }
  const f = acc / tot;
  if (w >= h) { layout(rows.slice(0, k), x, y, w * f, h, out); layout(rows.slice(k), x + w * f, y, w * (1 - f), h, out); }
  else { layout(rows.slice(0, k), x, y, w, h * f, out); layout(rows.slice(k), x, y + h * f, w, h * (1 - f), out); }
  return out;
}

function drawAlloc(sel) {
  const seg = (list, label) => `<p class="seg-lbl">${label}</p><div class="scroll-x"><div class="seg small" role="group" aria-label="${label}">${list.map(([k, l]) => `<button type="button" data-a="w-by" data-v="${k}" aria-pressed="${S.by === k}">${l}</button>`).join("")}</div></div>`;
  fill($("bySeg"), seg(BY.map((k) => [k, FACET[k].label]), "Tes choix") + seg(LOOK, "Contenu des fonds"));
  const a = allocRows(sel);
  const tm = $("tm");
  if (a.error || a.loading) {
    fill(tm, "");
    fill($("tmHint"), "");
    fill($("allocList"), a.error ? `<div class="err-box" role="alert">Composition indisponible : ${esc(a.error)}</div>` : skel("block"));
    return;
  }
  const rows = a.rows.filter((r) => r.v > 0);
  const owed = a.rows.filter((r) => r.v < 0).reduce((t, r) => t + r.v, 0);
  const total = rows.reduce((t, r) => t + r.v, 0);
  if (!rows.length || total <= 0) {
    fill(tm, "");
    fill($("tmHint"), "");
    fill($("allocList"), `<div class="empty">${a.fund ? "Aucune composition de fonds connue pour l'instant." : "Rien à répartir avec ces filtres."}</div>`);
    fill($("allocSum"), "<span>Rien à répartir</span>");
    return;
  }
  const act = (r) => (a.fund ? `data-a="w-bucket" data-v="${esc(r.k)}"` : `data-a="w-alloc" data-v="${esc(r.k)}"`);
  const cells = layout(rows, 0, 0, 340, 200);
  fill(tm, cells.map(({ r, x, y, w, h }) => {
    const big = w > 70 && h > 38, mid = w > 38 && h > 20, on = !a.fund && S.filters[S.by].has(r.k);
    return `<g class="tm-cell${on ? " on" : ""}" ${act(r)}><rect x="${(x + 1.5).toFixed(1)}" y="${(y + 1.5).toFixed(1)}" width="${Math.max(0, w - 3).toFixed(1)}" height="${Math.max(0, h - 3).toFixed(1)}" rx="6" data-css="--c:${r.c}"/>
      ${big ? `<text class="tm-n" x="${(x + 9).toFixed(1)}" y="${(y + 19).toFixed(1)}">${esc(r.name.length > w / 7.5 ? `${r.name.slice(0, Math.max(3, Math.floor(w / 7.5) - 1))}…` : r.name)}</text><text class="tm-v" x="${(x + 9).toFixed(1)}" y="${(y + 35).toFixed(1)}">${pf(r.v / total, 0)} %</text>`
        : mid ? `<text class="tm-v" x="${(x + 6).toFixed(1)}" y="${(y + h / 2 + 4).toFixed(1)}">${pf(r.v / total, 0)} %</text>` : ""}</g>`;
  }).join(""));
  fill($("tmHint"), a.fund
    ? `Sur tous tes placements${S.by === "currency" ? " et tes liquidités" : ""}, vus à l'intérieur des fonds : les filtres ne s'y appliquent pas. Touche un bloc pour voir les actifs qui y contribuent.`
    : "La taille d'un bloc est sa part. Touche un bloc ou une ligne pour filtrer tout l'écran.");
  fill($("allocList"), rows.map((r) => `<button class="alloc-row" type="button" ${act(r)} ${a.fund ? 'aria-haspopup="dialog"' : `aria-pressed="${S.filters[S.by].has(r.k)}"`} aria-label="${esc(r.name)}, ${share(r.v / total)}, ${a.fund ? "voir les actifs" : "filtrer sur cette valeur"}">
      ${r.mark}<span class="alloc-name">${esc(r.name)}</span>
      <span class="alloc-pct num">${share(r.v / total)}</span><span class="alloc-val">${amount(r.v)}</span></button>`).join("") +
    (owed < 0 ? `<div class="alloc-row static">${facetMark("cat", "debt")}<span class="alloc-name">Dettes, retranchées</span><span class="alloc-pct"></span><span class="alloc-val">${amount(owed)}</span></div>` : ""));
  const label = a.fund ? LOOK.find(([k]) => k === S.by)[1] : FACET[S.by].label;
  fill($("allocSum"), `<span class="ministack">${rows.map((r) => `<i data-css="--f:${r.v.toFixed(2)};--c:${r.c}"></i>`).join("")}</span><span>${label} : ${rows.slice(0, 3).map((r) => `${esc(r.name)} ${share(r.v / total)}`).join(" · ")}</span>`);
}

SHEETS.bucket = (k) => {
  const a = current ? allocRows(current.sel) : null;
  const r = a && a.rows ? a.rows.find((x) => x.k === k) : null;
  if (!r) return null;
  const total = a.rows.filter((x) => x.v > 0).reduce((t, x) => t + x.v, 0);
  const cash = S.by === "currency" ? sum(current.all.filter((l) => l.asset === `ccy:${r.k}` && l.kind !== "debt" && l.value > 0)) : 0;
  return {
    title: `${r.mark}${esc(r.name)}`,
    body: `<div class="sheet-big num">${share(r.v / total)} <small>· ${amount(r.v)}</small></div>
      <p class="hint">Un fonds est réparti sur plusieurs blocs : ces actifs y contribuent pour une part, sans filtre sur l'écran.</p>
      <div class="list">${r.assets.map((x) => {
        const l = current.all.find((y) => y.asset === `isin:${x.isin}`);
        return `<button class="sub-row" type="button" data-a="w-bucket-go" data-v="s:isin:${esc(x.isin)}">${l ? assetMark(l, "sm") : facetMark("cat", "funds")}
          <span class="row-main"><span class="row-title">${esc(x.name)}</span><span class="row-sub">${share(units(x.value) / r.v)} du bloc</span></span>
          <span class="row-num"><span class="num sub-val">${amount(units(x.value))}</span></span><span class="go">${ic("chev")}</span></button>`;
      }).join("")}${cash >= 1 ? `<div class="sub-row static">${facetMark("cat", "cash")}<span class="row-main"><span class="row-title">Liquidités</span><span class="row-sub">comptes en ${esc(r.name)}</span></span><span class="row-num"><span class="num sub-val">${amount(cash)}</span></span><span></span></div>` : ""}</div>`,
  };
};

function tagsFor(ls) {
  const ks = [S.by, "cat", "liq", "goal"].filter((k, i, a) => a.indexOf(k) === i && k !== "inst");
  return `<span class="tags">${ks.flatMap((k) => [...new Set(ls.map((l) => l[k]))].filter((v) => v != null).map((v) => `<span class="tag${k === S.by ? " cur" : ""}" title="${FACET[k].label}">${facetIc(k, v)}${esc(facetName(k, v))}</span>`)).join("")}</span>`;
}

const rowId = (key) => `row-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
const accLabel = (l) => (l.inst === l.accName ? l.accName : `${l.inst} · ${l.accName}`);

// gain et rendement d'une ligne du détail : le serveur les donne par compte, par actif, par ligne
function statsFor(view, ls) {
  const f = ls[0];
  const perf = f.kind === "debt" ? current.net : current.perf;
  if (!perf) return null;
  return view === "acc" ? perf.by_account[f.acc] : perf.by_asset[f.asset];
}
const isCash = (view, f) => f.kind !== "debt" && (view === "acc" ? f.kind === "cash" : f.asset.startsWith("ccy:"));

function drawPerf() {
  const n = activeCount();
  const perf = current.perf;
  fill($("perfSum"), perfSummary(perf, per().label));
  $("perfNote").textContent = per().label;
  if (FOLD.perf) return fill($("tabBody"), "");
  fill($("tabSeg"), TABS.map(([k, l]) => `<button type="button" data-a="w-tab" data-v="${k}" aria-pressed="${S.tab === k}">${l}</button>`).join(""));
  const asOf = current.h.as_of;
  const ctx = {
    S, n, per: per(), perf, src: current.src, all: current.all, sel: current.sel, pts, asOf,
    fmtDate,
  };
  fill($("tabBody"), perfSection(ctx));
}

function drawList(all, sel) {
  const items = current.items;
  fill($("viewSeg"), [["acc", "Comptes"], ["asset", "Actifs"]].map(([k, l]) => `<button type="button" data-a="w-view" data-v="${k}" aria-pressed="${S.view === k}">${l}</button>`).join(""));
  const so = SORTS.find((s) => s.k === S.sort);
  fill($("sortBtn"), `Trier : ${so.label}${ic("sort")}`);
  $("sortBtn").setAttribute("aria-label", `Trier par ${so.label}, toucher pour changer`);
  const groups = Object.groupBy(sel, (l) => (S.view === "acc" ? `a:${l.acc}` : `s:${l.asset}`));
  let rows = Object.entries(groups).map(([key, ls]) => {
    const f = ls[0];
    const c = statsFor(S.view, ls);
    if (f.kind === "debt") {
      return { key, ls, title: f.name, sub: `${esc(f.inst)} · ${DEBT_KIND[f.debtKind] || "Dette"}`, mark: debtMark({ kind: f.debtKind }, ""), value: sum(ls), c, debt: f.debt };
    }
    if (S.view === "acc") {
      const totalLines = all.filter((l) => l.acc === f.acc).length;
      return { key, ls, title: f.accName, sub: `${esc(f.inst)} · ${KIND_LABEL[f.kind] || ""}`, mark: facetMark("inst", f.inst, ""), value: sum(ls), c, cash: isCash("acc", f),
        partial: ls.length < totalLines ? `${ls.length} ligne${ls.length > 1 ? "s" : ""} sur ${totalLines} selon les filtres` : "" };
    }
    const q = ls.reduce((t, l) => t + Number(l.qty), 0);
    const where = ls.length > 1 ? `dans ${ls.length} comptes` : esc(accLabel(f));
    return { key, ls, title: f.name, sub: `<span class="money">${qty(q)}</span> ${esc(f.unit)} · ${where}`, mark: assetMark(f), value: sum(ls), c, cash: isCash("asset", f) };
  });
  const gainOf = (r) => (r.c ? units(r.c.gain) : -Infinity);
  rows.sort(S.sort === "val" ? (a, b) => b.value - a.value : S.sort === "chg" ? (a, b) => gainOf(b) - gainOf(a) : (a, b) => a.title.localeCompare(b.title, "fr"));
  rows = rows.filter((r) => Math.abs(r.value) >= 0.5 || S.view === "acc");
  $("listCount").textContent = `${rows.length} ${S.view === "acc" ? "compte" : "actif"}${rows.length > 1 ? "s" : ""}`;
  if (!rows.length) {
    fill($("list"), '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>');
    return;
  }
  const total = sel.reduce((t, l) => t + Math.max(0, l.value), 0); // parts des avoirs, dettes à part
  fill($("list"), rows.map((r) => {
    const open = S.open.has(r.key);
    // deux lignes : nom, puis institution et nature ; le reste (part, étiquettes) est au dépliage
    return `<div id="${rowId(r.key)}"><button class="row row2" type="button" data-a="w-row" data-v="${esc(r.key)}" aria-expanded="${open}">
      ${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}</span><span class="row-sub">${r.sub}${r.partial ? ` · <span class="partial">${r.partial}</span>` : ""}</span></span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta">${rowDelta(r, items)}</span></span>
    </button>${open ? `<div class="sub">${r.debt ? `${debtCurve(r)}${debtDetail(r.debt)}${journalLink(r)}` : `${perfStrip(r, total)}${S.view === "acc" ? accountDetail(r, all) : assetDetail(r)}${journalLink(r)}${rowFoot(r)}`}</div>` : ""}</div>`;
  }).join(""));
}

// à droite d'une ligne : gain · rendement ; apports pour un compte bancaire, intérêts pour une dette
function rowDelta(r, items) {
  if (!items || items.length < 2 || !r.c) return "";
  const g = units(r.c.gain);
  if (r.debt) return `<span class="delta ${tone(g)} num">${signedMoney(g)}</span> <span class="faint">intérêts</span>`;
  if (r.cash) return `<span class="faint num">apports ${signedMoney(units(r.c.net_flows))}</span>`;
  return gainSpan(g, rate(r.c.twr)).replace(` ${base()}`, "");
}

// en tête du dépliage : gain, rendement, rendement annuel, puis le pont de la période
function perfStrip(r, total) {
  const c = r.c;
  const part = `<div><span>Part</span><b class="num">${total > 0 ? share(r.value / total) : "—"}</b></div>`;
  if (!c || !current.items || current.items.length < 2) return `<div class="strip">${part}</div>`;
  const g = units(c.gain), twr = rate(c.twr), yr = rate(c.twr_yearly);
  if (r.cash) {
    return `<div class="strip"><div><span>Apports nets</span><b class="num">${signedMoney(units(c.net_flows))}</b></div><div><span>Intérêts</span><b class="num ${tone(g)}">${signedMoney(g)}</b></div>${part}</div>`;
  }
  const open = S.bridge.has(r.key);
  return `<div class="strip"><div><span>Gain</span><b class="num ${tone(g)}">${signedMoney(g)}</b></div><div><span>Rendement</span><b class="num ${tone(twr)}">${ratePct(twr)}</b></div><div><span>Par an</span><b class="num ${tone(yr)}">${yr == null ? "—" : ratePct(yr)}</b></div>${part}</div>
    ${c.complete ? "" : '<p class="pnote">Des cours manquent sur la période : chiffres partiels.</p>'}
    <button class="linkish bridge-btn" type="button" data-a="w-bridge" data-v="${esc(r.key)}" aria-expanded="${open}">${open ? "Masquer le détail" : `D'où vient la valeur · ${per().label}`}${ic("down")}</button>${open ? bridge(c) : ""}`;
}

// solde de la dette sur la période : sa propre série, une ligne seule
function debtCurve(r) {
  const h = current.h;
  if (!h || !h.items.length) return "";
  const e = store.use(perfPath(startDate(h), per().step, [lineId(r.ls[0])]));
  const vs = e.data ? e.data.items.map((it) => -units(it.value)) : [];
  if (vs.length < 2) return "";
  const mx = Math.max(...vs, 1), w = 300, hh = 46;
  const d = vs.map((v, i) => `${i ? "L" : "M"}${((i / (vs.length - 1)) * w).toFixed(1)},${(4 + (hh - 8) * (1 - v / mx)).toFixed(1)}`).join("");
  const paid = vs[0] - vs[vs.length - 1];
  return `<div class="sub-head"><span>Solde ${per().label}</span><b class="num">${paid > 0 ? `<span class="money">${n0(paid)}</span> ${base()} remboursés` : paid < 0 ? `+<span class="money">${n0(-paid)}</span> ${base()}` : "inchangé"}</b></div>
    <svg class="chart debtcurve" viewBox="0 0 ${w} ${hh}" preserveAspectRatio="none" role="img" aria-label="Solde de la dette, de ${n0(vs[0])} à ${n0(vs[vs.length - 1])} ${base()}"><path d="${d}L${w},${hh}L0,${hh}Z" class="fillneg"/><path d="${d}" class="lineneg"/></svg>`;
}

// vers le journal filtré sur ce compte, cet actif ou les paiements de cette dette
function journalLink(r) {
  const f = r.ls[0];
  const what = r.debt ? "Voir les paiements" : S.view === "acc" ? (r.cash ? "Voir les écritures du compte" : "Voir les écritures du compte") : f.asset.startsWith("isin:") ? "Voir les achats et ventes" : "Voir les écritures";
  return `<button class="sub-row jlink" type="button" data-a="w-journal" data-v="${esc(r.key)}"><span class="ibox sm tint" data-css="--c:var(--accent)" aria-hidden="true">${ic("list")}</span>
    <span class="row-main"><span class="row-title">${what}</span><span class="row-sub">Journal filtré, le retour revient ici</span></span><span></span><span class="go">${ic("chev")}</span></button>`;
}

// pied du dépliage : nature, objectif et étiquettes ; Modifier pour un compte
function rowFoot(r) {
  const f = r.ls[0];
  return `<div class="row-foot">${tagsFor(r.ls)}${S.view === "acc" && f.kind !== "debt" ? `<button class="linkish" type="button" data-a="acc-edit" data-v="${esc(f.acc)}">Modifier</button>` : ""}</div>`;
}

// pont : départ, versements, revenus, plus-values et change, frais, arrivée
function bridge(c) {
  const steps = [["Début", units(c.start), true], ["Apports", units(c.net_flows)], ["Revenus", units(c.income)], ["Plus-val.", units(c.price_effect)], ["Frais", units(c.fees)], ["Fin", units(c.end), true]];
  let run = 0, top = 0, low = 0;
  for (const [, v, b] of steps) { run = b ? v : run + v; top = Math.max(top, run); low = Math.min(low, run); }
  const span = top - low || 1, BH = 124, bw = 46, gap = 10;
  const Y = (v) => 16 + (BH - 34) * (1 - (v - low) / span);
  run = 0;
  const bars = steps.map(([name, v, b], k) => {
    const y0 = b ? 0 : run, y1 = b ? v : run + v;
    run = y1;
    const t = Y(Math.max(y0, y1)), h = Math.max(1.5, Math.abs(Y(y0) - Y(y1)));
    const x = 4 + k * (bw + gap);
    const label = b ? `${n0(v / 1000)}k` : `${sgn(v)}${n0(v)}`;
    return `<rect class="${b ? "base" : v >= 0 ? "pos" : "neg"}" x="${x}" y="${t.toFixed(1)}" width="${bw}" height="${h.toFixed(1)}" rx="3"/><text class="money val" x="${x + bw / 2}" y="${(t - 3).toFixed(1)}" text-anchor="middle">${label}</text><text x="${x + bw / 2}" y="${BH - 5}" text-anchor="middle">${name}</text>`;
  }).join("");
  return `<svg class="chart bridge" viewBox="0 0 340 ${BH}" role="img" aria-label="De ${n0(units(c.start))} à ${n0(units(c.end))} ${base()} : apports ${n0(units(c.net_flows))}, revenus ${n0(units(c.income))}, plus-values ${n0(units(c.price_effect))}, frais ${n0(units(c.fees))}">${bars}</svg>`;
}

function unitPrice(l) {
  if (l.asset.startsWith("ccy:")) return l.unit === base() ? "" : ` · cours ${(Math.abs(l.value / Number(l.qty)) || 0).toFixed(3).replace(".", ",")}`;
  return l.price ? ` × <span class="money">${n2(Number(l.price))}</span> ${esc(l.priceCcy || "")}` : " · sans cours";
}

function accountDetail(r, all) {
  const ls = r.ls.slice().sort((a, b) => b.value - a.value), tot = sum(ls) || 1;
  const items = current.items;
  const byLine = current.perf ? current.perf.by_line : {};
  const f = ls[0];
  return `<div class="sub-head"><span>Composition du compte · objectif <b>${esc(facetName("goal", f.goal))}</b></span></div>
    <div class="compo" aria-hidden="true">${ls.map((l) => `<i data-css="--f:${Math.max(0, l.value).toFixed(2)};--c:${facetColor("cat", l.cat)}"></i>`).join("")}</div>
    ${ls.map((l) => {
      const c = byLine[lineId(l)];
      const pc = items && items.length > 1 && c && !l.asset.startsWith("ccy:") ? ` · ${pctOnly(rate(c.twr))}` : "";
      return `<button class="sub-row" type="button" data-a="w-jump" data-v="s:${esc(l.asset)}" aria-label="${esc(l.name)}, ${share(l.value / tot)} du compte. Voir cet actif dans la vue Actifs">
        ${assetMark(l, "sm")}
        <span class="row-main"><span class="row-title">${esc(l.name)}</span><span class="row-sub"><span class="money">${qty(l.qty)}</span> ${esc(l.unit)}${unitPrice(l)}</span></span>
        <span class="row-num"><span class="num sub-val">${amount(l.value)}</span><span class="sub-share">${share(l.value / tot)}${pc}</span></span>
        <span class="go">${ic("chev")}</span></button>`;
    }).join("")}`;
}

function assetDetail(r) {
  const ls = r.ls.slice().sort((a, b) => b.value - a.value), tot = sum(ls) || 1;
  const f = ls[0];
  const q = ls.reduce((t, l) => t + Number(l.qty), 0);
  return `<div class="sub-head"><span>Où se trouve cet actif</span><b><span class="money">${qty(q)}</span> ${esc(f.unit)}${f.price ? ` · cours <span class="money">${n2(Number(f.price))}</span> ${esc(f.priceCcy || "")}` : ""}</b></div>
    <div class="compo" aria-hidden="true">${ls.map((l) => `<i data-css="--f:${Math.max(0, l.value).toFixed(2)};--c:${facetColor("inst", l.inst)}"></i>`).join("")}</div>
    ${ls.map((l) => `<button class="sub-row" type="button" data-a="w-jump" data-v="a:${esc(l.acc)}" aria-label="${esc(accLabel(l))}, ${share(l.value / tot)} de cet actif. Voir ce compte dans la vue Comptes">
        ${facetMark("inst", l.inst, "sm")}
        <span class="row-main"><span class="row-title">${esc(accLabel(l))}</span><span class="row-sub"><span class="money">${qty(l.qty)}</span> ${esc(l.unit)} · ${esc(facetName("liq", l.liq))}</span>
          <span class="minibar" data-css="--c:${facetColor("inst", l.inst)}"><i data-css="width:${Math.max(0, Math.min(100, (l.value / tot) * 100)).toFixed(1)}%"></i></span></span>
        <span class="row-num"><span class="num sub-val">${amount(l.value)}</span><span class="sub-share">${share(l.value / tot)} de l'actif</span></span>
        <span class="go">${ic("chev")}</span></button>`).join("")}`;
}

// --- panneaux ---------------------------------------------------------------------------------

SHEETS.filters = () => {
  const all = lines() || [];
  const n = activeCount();
  return {
    title: "Filtres",
    act: n ? '<button class="clear-link" type="button" data-a="w-clear">Tout effacer</button>' : "",
    body: FACETS.map((f) => {
      const k = S.filters[f.key].size;
      return `<div class="facet" role="group" aria-label="${f.label}"><div class="facet-head">${f.label}<span>${k ? `${k} choisi${k > 1 ? "s" : ""}` : "Tous"}</span></div><div class="opts">${f.values.map((v) => {
        const val = sum(all.filter((l) => l[f.key] === v && match(l, f.key))), on = S.filters[f.key].has(v);
        return `<button class="opt" type="button" data-a="w-opt" data-v="${f.key}|${esc(v)}" aria-pressed="${on}" ${Math.abs(val) < 0.5 && !on ? "disabled" : ""}>${facetMark(f.key, v, "xs")}<span><b>${esc(facetName(f.key, v))}</b><span>${Math.abs(val) >= 0.5 ? amount(val) : "aucun avoir"}</span></span></button>`;
      }).join("")}</div></div>`;
    }).join(""),
    foot: `<button class="primary num" type="button" data-a="sheet-close" data-autofocus>Afficher ${amount(sum(all.filter((l) => match(l))))}</button>`,
  };
};

// --- actions ----------------------------------------------------------------------------------

function toggle(key, v) {
  const s = S.filters[key];
  if (s.has(v)) s.delete(v);
  else s.add(v);
  S.scrub = null;
}
const snap = () => ({ filters: Object.fromEntries(FACETS.map((f) => [f.key, new Set(S.filters[f.key])])), by: S.by });
// la répartition filtrée sur une seule valeur passe à l'axe suivant qui a encore plusieurs valeurs
function autoBy() {
  const sel = (lines() || []).filter((l) => match(l));
  if (new Set(sel.map((l) => l[S.by])).size > 1) return null;
  for (const k of BY) {
    if (k !== S.by && new Set(sel.map((l) => l[k])).size > 1) {
      S.by = k;
      return k;
    }
  }
  return null;
}
const announceSel = () => announce(`Sélection : ${n0(sum((lines() || []).filter((l) => match(l))))} ${base()}`);

export function only(key, v) {
  for (const f of FACETS) S.filters[f.key].clear();
  S.filters[key].add(v);
  S.scrub = null;
  if (S.by === key) autoBy();
}

export const actions = {
  filters: () => openSheet("filters"),
  "w-opt": (v) => {
    const i = v.indexOf("|");
    toggle(v.slice(0, i), v.slice(i + 1));
    store.notify();
    announceSel();
  },
  "w-clear": () => {
    for (const f of FACETS) S.filters[f.key].clear();
    store.notify();
    announceSel();
  },
  "w-by": (v) => { S.by = v; remember(); store.notify(); },
  "w-alloc": (v) => {
    const prev = snap(), adding = !S.filters[S.by].has(v), name = facetName(S.by, v);
    toggle(S.by, v);
    const nb = adding ? autoBy() : null;
    remember();
    store.notify();
    announceSel();
    const undo = () => { S.filters = prev.filters; S.by = prev.by; };
    if (nb) toast(`Filtré sur « ${name} ». Répartition par ${FACET[nb].label.toLowerCase()}.`, { undo });
    else if (adding) toast(`Filtré sur « ${name} ».`, { undo });
  },
  "w-mode": (v) => { S.mode = v; remember(); store.notify(); },
  "w-tab": (v) => { S.tab = v; remember(); store.notify(); },
  // une tuile qui filtre l'écran (la réserve : les liquidités)
  "w-only": (v) => {
    const i = v.indexOf("|");
    only(v.slice(0, i), v.slice(i + 1));
    remember();
    if (store.params.tab !== "patrimoine") go("patrimoine", { top: true });
    else window.scrollTo({ top: 0 });
    store.notify();
    announceSel();
  },
  "w-period": (v) => { S.period = v; S.scrub = null; remember(); store.notify(); },
  "w-view": (v) => { S.view = v; remember(); store.notify(); },
  "w-sort": () => {
    const i = SORTS.findIndex((s) => s.k === S.sort);
    S.sort = SORTS[(i + 1) % SORTS.length].k;
    remember();
    store.notify();
  },
  "w-row": (v) => {
    if (S.open.has(v)) S.open.delete(v);
    else S.open.add(v);
    store.notify();
  },
  // bascule vers l'autre vue, élément ouvert et éclairé
  "w-jump": (v) => {
    S.view = v[0] === "s" ? "asset" : "acc";
    S.open.add(v);
    remember();
    render();
    const node = $(rowId(v));
    if (node) {
      reveal(node, $("detailHead").offsetHeight);
      node.classList.remove("flash");
      void node.offsetWidth;
      node.classList.add("flash");
      node.querySelector(".row").focus({ preventScroll: true });
    }
    announce(`Vue ${S.view === "acc" ? "Comptes" : "Actifs"}`);
  },
  "w-gross": (v) => {
    S.gross = v === "gross";
    S.scrub = null;
    remember();
    store.notify();
    announce(S.gross ? "Brut : dettes exclues" : "Net : dettes comprises");
  },
  "w-bridge": (v) => {
    if (S.bridge.has(v)) S.bridge.delete(v);
    else S.bridge.add(v);
    store.notify();
  },
  "w-bucket": (k) => openSheet("bucket", k),
  "w-bucket-go": (v) => {
    closeSheet(true);
    actions["w-jump"](v);
  },
  // le journal filtré ; le retour (geste ou bouton) revient sur la ligne, dépliée
  "w-journal": (key) => {
    const ls = (lines() || []).filter((l) => (key.startsWith("a:") ? `a:${l.acc}` : `s:${l.asset}`) === key);
    const f = ls[0];
    if (!f) return;
    let spec;
    if (f.kind === "debt") {
      const d = (store.data(paths.debts) || { items: [] }).items.find((x) => x.id === f.debt) || {};
      spec = { kind: "debt", id: f.debt, label: `Dette : ${f.name}`, jf: { ...(d.category_id ? { category: d.category_id } : {}), ...(d.account_id ? { account: d.account_id } : {}) } };
    } else if (key.startsWith("a:")) spec = { kind: "acc", id: f.acc, label: `Compte : ${accLabel(f)}`, jf: { account: f.acc } };
    else if (f.asset.startsWith("isin:")) {
      const accs = [...new Set(ls.map((l) => l.acc))];
      spec = { kind: "asset", id: f.asset, label: `Actif : ${f.name}`, asset: { isin: f.asset.slice(5), account: accs.length === 1 ? accs[0] : null } };
    } else spec = { kind: "acc", id: f.acc, label: `Compte : ${accLabel(f)}`, jf: { account: f.acc } };
    go("journal", { link: linkTo(spec), top: true });
  },
  "w-fold": (k) => {
    FOLD[k] = !FOLD[k];
    setPref("fold", FOLD);
    store.notify();
  },
};

