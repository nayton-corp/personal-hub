// Patrimoine : une sélection (filtres par catégorie, disponibilité, objectif, institution) pilote
// tout l'écran : total et courbe, répartition, performance, puis le détail par compte ou par
// actif, chacun dépliable et relié à l'autre. Les lignes viennent de /finance/accounts et
// /finance/holdings ; la courbe, le gain et le rendement, de /finance/performance pour les lignes
// choisies (les versements n'y sont pas du gain). Les dettes (/finance/debts) sont des lignes
// négatives de catégorie « Dettes » : le total est net.
import { DEBT_KIND, debtDetail, debtMark } from "./debts.js";
import { reveal } from "./finance.js";
import { MOIS, MOIS_L, base, date } from "./format.js";
import { gainSpan, perfSection, perfSummary, rate, ratePct, signedMoney, tone, units } from "./perf.js";
import { CCY_NAME, FACET, FACETS, assetMark, facetColor, facetIc, facetMark, facetName, setInstitutions } from "./meta.js";
import { shiftMonth, store } from "./store.js";
import {
  SHEETS, amount, announce, esc, fill, ic, money, n0, n2, openSheet, pctOnly, pf, pref, qty, setPref, sgn, share, toast,
} from "./ui.js";

const $ = (id) => document.getElementById(id);
const paths = { accounts: "/finance/accounts", holdings: "/finance/holdings", history: "/finance/networth/history", fresh: "/finance/freshness", debts: "/finance/debts" };
const KIND_LABEL = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto", debt: "Dette" };
const PERIODS = [
  { k: "1M", label: "sur 1 mois", days: 30, def: "J" },
  { k: "3M", label: "sur 3 mois", days: 91, def: "J" },
  { k: "YTD", label: "depuis le 1er janvier", def: "S" },
  { k: "1A", label: "sur 1 an", days: 365, def: "S" },
  { k: "5A", label: "sur 5 ans", days: 1826, def: "M" },
  { k: "Max", label: "depuis le début", def: "M" },
];
const GRAN = { J: { label: "Jour", step: "day", days: 1 }, S: { label: "Semaine", step: "week", days: 7 }, M: { label: "Mois", step: "month", days: 30 } };
const BY = ["cat", "liq", "goal", "inst"];
const SORTS = [{ k: "val", label: "Valeur" }, { k: "chg", label: "Gain" }, { k: "az", label: "Nom" }];
const MODES = [["val", "Valeur"], ["gain", "Gain"], ["rend", "Rendement"]];
const TABS = [["rend", "Rendement"], ["rev", "Revenus et frais"], ["risk", "Risque"], ["traj", "Trajectoire"]];
const MAX_POINTS = 400;
const W = 340, H = 170, L = 2, R = 2, T = 10, BOT = 22;

const saved = pref("wealth", {});
const S = {
  filters: { cat: new Set(), liq: new Set(), goal: new Set(), inst: new Set() },
  by: BY.includes(saved.by) ? saved.by : "cat",
  period: PERIODS.some((p) => p.k === saved.period) ? saved.period : "1A",
  gran: GRAN[saved.gran] ? saved.gran : "S",
  mode: saved.mode === "perf" ? "rend" : MODES.some(([k]) => k === saved.mode) ? saved.mode : "val",
  tab: TABS.some(([k]) => k === saved.tab) ? saved.tab : "rend",
  tax: typeof saved.tax === "number" ? saved.tax : 0.25,
  view: saved.view === "asset" ? "asset" : "acc",
  sort: SORTS.some((s) => s.k === saved.sort) ? saved.sort : "val",
  open: new Set(),
  scrub: null,
};
const FOLD = { evo: false, alloc: false, perf: true, ...pref("fold", {}) };
let pts = []; // points de la courbe affichée

function remember() {
  const { by, period, gran, mode, view, sort, tab, tax } = S;
  setPref("wealth", { by, period, gran, mode, view, sort, tab, tax });
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

function grans(h) {
  const days = Math.round((day(h.as_of) - day(startDate(h))) / 864e5);
  return Object.keys(GRAN).filter((g) => (g === "M" ? days >= 85 : days / GRAN[g].days <= MAX_POINTS));
}

export const perfPath = (from, step, ids) =>
  `/finance/performance?${from ? `from=${from}&` : ""}step=${step}${ids ? ids.map((i) => `&line=${encodeURIComponent(i)}`).join("") : ""}`;

// lignes demandées : aucune sans filtre (le serveur prend celles de l'app), sinon la sélection ;
// « compte|cash » porte aussi les revenus et frais d'un compte à positions (sans valeur)
function selIds(sel) {
  if (!activeCount()) return null;
  const ids = new Set(sel.map(lineId));
  for (const l of sel) if (l.kind !== "debt") ids.add(`${l.acc}|cash`);
  return [...ids].sort();
}

function seriesSource(h, sel) {
  if (!sel.length) return { items: [], status: "ok", data: null };
  const e = store.use(perfPath(startDate(h), GRAN[S.gran].step, selIds(sel)));
  return { items: e.data ? e.data.items : null, status: e.status, error: e.error, data: e.data };
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
        <div class="chart-opts"><div class="seg small" id="modeSeg" role="group" aria-label="Mesure"></div><div class="seg small" id="granSeg" role="group" aria-label="Un point par"></div></div>
      </div>
      <div id="heroFoot"></div>
    </div>
    <section class="section" id="alloc" aria-labelledby="t-alloc">
      <div class="section-head"><button class="fold-btn" type="button" data-a="w-fold" data-v="alloc" aria-controls="alloc-body"><h2 class="section-title" id="t-alloc">Répartition</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
      <button class="sec-sum" id="allocSum" type="button" data-a="w-fold" data-v="alloc" aria-label="Déplier la répartition"></button>
      <div class="sec-body" id="alloc-body">
        <div class="scroll-x"><div class="seg small" id="bySeg" role="group" aria-label="Répartir par"></div></div>
        <div class="stack" id="stack" aria-hidden="true"></div>
        <div class="alloc-list" id="allocList"></div>
        <p class="hint">Toucher une ligne filtre tout l'écran sur cette valeur.</p>
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
    fill($("hero"), err ? `<div class="err-box" role="alert">Impossible de charger le patrimoine : ${esc(err.error.message)}</div>` : '<div class="loading">Chargement…</div>');
    for (const id of ["heroFoot", "list", "allocList", "stack", "allocSum", "perfSum", "tabBody", "legend"]) fill($(id), "");
    $("chart").replaceChildren();
    return;
  }
  const h = hi.data;
  const sel = all.filter((l) => match(l));
  const src = h.items.length ? seriesSource(h, sel) : { items: [], status: "ok", data: null };
  current = { all, sel, items: src.items, h, src, perf: src.data };
  for (const k of ["evo", "alloc", "perf"]) {
    $(k).classList.toggle("folded", FOLD[k]);
    const b = $(k).querySelector(".fold-btn");
    if (b) b.setAttribute("aria-expanded", String(!FOLD[k]));
  }
  drawControls(h);
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

function drawControls(h) {
  fill($("modeSeg"), MODES.map(([k, l]) => `<button type="button" data-a="w-mode" data-v="${k}" aria-pressed="${S.mode === k}">${l}</button>`).join(""));
  fill($("periods"), PERIODS.map((p) => `<button class="pchip" type="button" data-a="w-period" data-v="${p.k}" aria-pressed="${S.period === p.k}" aria-label="Période ${p.label}">${p.k}</button>`).join(""));
  const gs = h.items.length ? grans(h) : ["M"];
  if (!gs.includes(S.gran)) S.gran = gs.includes(per().def) ? per().def : gs[gs.length - 1];
  $("granSeg").hidden = gs.length < 2;
  fill($("granSeg"), gs.map((g) => `<button type="button" data-a="w-gran" data-v="${g}" aria-pressed="${S.gran === g}">${GRAN[g].label}</button>`).join(""));
}

function heroTop(scrubbed) {
  const { sel } = current;
  const n = activeCount();
  const scrub = scrubbed != null;
  const first = pts[0], p = scrub ? pts[scrubbed] : pts[pts.length - 1];
  const v = scrub ? p.v : sum(sel);
  fill($("hero"), `
    <div class="hero-label">${scrub ? `<span class="scrub-date">${fmtDate(p.d, true)}</span>` : `<span>${n ? "Sélection filtrée" : "Patrimoine total"}</span>`}</div>
    <div class="hero-amount num"><span class="money">${n0(v)}</span><small>${base()}</small></div>
    <div class="hero-delta">${pts.length > 1 ? `${gainSpan(p.g, p.r)}<span class="period-link">de gain ${scrub ? `depuis le ${fmtDate(first.d, true)}` : per().label}</span>` : ""}</div>
    ${pts.length > 1 ? `<div class="hero-sub num">${n ? "Apports nets" : "Épargne"} ${signedMoney(p.f)} · variation totale ${signedMoney(p.v - first.v)}</div>` : ""}`);
  fill($("miniTotal"), `${n ? "Sélection · " : ""}${money(sum(sel))} ${base()}`);
}

function drawChart() {
  if (!current) return;
  const { sel, items, src, perf } = current;
  const svg = $("chart");
  const est = $("estimate");
  pts = (items || []).map((it) => ({ d: it.on_date, v: units(it.value), f: units(it.net_flows), g: units(it.gain), r: rate(it.twr), dd: rate(it.drawdown), ok: it.complete }));
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
  let mn = Math.min(...ys, ...(dep || [])), mx = Math.max(...ys, ...(dep || []));
  if (S.mode !== "val") { mn = Math.min(mn, 0); mx = Math.max(mx, 0); }
  const pad = (mx - mn) * 0.08 || Math.abs(mx) * 0.05 || 1;
  mn -= pad; mx += pad;
  const X = (i) => L + (W - L - R) * (i / (pts.length - 1)), Y = (v) => T + (H - T - BOT) * (1 - (v - mn) / (mx - mn));
  const path = (vs) => vs.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const line = path(ys);
  let under = "";
  if (dep) {
    // entre la valeur et les versements : vert quand le marché a ajouté, rouge quand il a retiré
    for (let i = 1; i < ys.length; i++) {
      const up = ys[i] + ys[i - 1] >= dep[i] + dep[i - 1];
      under += `<path class="zone ${up ? "pos" : "neg"}" d="M${X(i - 1).toFixed(1)},${Y(ys[i - 1]).toFixed(1)}L${X(i).toFixed(1)},${Y(ys[i]).toFixed(1)}L${X(i).toFixed(1)},${Y(dep[i]).toFixed(1)}L${X(i - 1).toFixed(1)},${Y(dep[i - 1]).toFixed(1)}Z"/>`;
    }
    under += `<path class="dep" d="${path(dep)}"/>`;
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
    ? `<span><i></i>Valeur</span><span><i class="dash"></i>Départ + ${activeCount() ? "apports nets" : "épargne"}</span><span>Écart vert : gain, rouge : perte</span>`
    : S.mode === "gain" ? `<span><i></i>Gain cumulé ${per().label}, versements exclus</span>`
    : '<span><i></i>Rendement pondéré dans le temps : les versements n\'y comptent pas</span>');
}

function drawFoot(all, sel) {
  const n = activeCount();
  const total = sum(sel), whole = sum(all);
  const nacc = new Set(sel.map((l) => l.acc)).size;
  const f = store.data(paths.fresh);
  const last = f ? f.items.map((x) => x.last_import).filter(Boolean).sort().pop() : null;
  const stale = last && Date.now() - Date.parse(last) > 3 * 864e5;
  const owed = sum(all.filter((l) => l.kind === "debt"));
  fill($("heroFoot"), `
    ${!n && owed < 0 ? `<div class="share">Avoirs ${amount(whole - owed)} · dettes ${amount(owed)}</div>` : ""}
    ${n && whole > 0 ? `<div class="share"><div class="sharebar"><i data-css="width:${Math.max(0, Math.min(100, (total / whole) * 100)).toFixed(1)}%"></i></div>${share(total / whole)} de ton patrimoine (${amount(whole)})</div>` : ""}
    <div class="hero-foot"><div class="fresh${stale ? " stale" : ""}"><i></i>${last ? `Mis à jour le ${date(last.slice(0, 10))}` : "Pas encore d'import"} · ${nacc} compte${nacc > 1 ? "s" : ""}</div>
    <button class="graph-toggle" type="button" data-a="w-fold" data-v="evo" aria-expanded="${!FOLD.evo}" aria-controls="evoBody">${FOLD.evo ? "Afficher la courbe" : "Masquer la courbe"}<svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>`);
}

function drawAlloc(sel) {
  fill($("bySeg"), BY.map((k) => `<button type="button" data-a="w-by" data-v="${k}" aria-pressed="${S.by === k}">${FACET[k].label}</button>`).join(""));
  const g = {};
  for (const l of sel) if (l[S.by] != null) g[l[S.by]] = (g[l[S.by]] || 0) + l.value;
  const rows = Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => b[1] - a[1]);
  // parts des avoirs : une dette s'y lit en négatif
  const total = rows.reduce((t, [, v]) => t + Math.max(0, v), 0);
  const flex = (v) => Math.max(0, v).toFixed(2);
  fill($("stack"), rows.map(([k, v]) => `<i data-css="--f:${flex(v)};--c:${facetColor(S.by, k)}"></i>`).join(""));
  fill($("allocList"), rows.length && total > 0 ? rows.map(([k, v]) => `<button class="alloc-row" type="button" data-a="w-alloc" data-v="${esc(k)}" aria-pressed="${S.filters[S.by].has(k)}" aria-label="${esc(facetName(S.by, k))}, ${share(v / total)}, filtrer sur cette valeur">
      ${facetMark(S.by, k)}<span class="alloc-name">${esc(facetName(S.by, k))}</span>
      <span class="alloc-pct num">${share(v / total)}</span><span class="alloc-val">${amount(v)}</span></button>`).join("") : '<div class="empty">Rien à répartir avec ces filtres.</div>');
  fill($("allocSum"), rows.length && total > 0
    ? `<span class="ministack">${rows.map(([k, v]) => `<i data-css="--f:${flex(v)};--c:${facetColor(S.by, k)}"></i>`).join("")}</span><span>${FACET[S.by].label} : ${rows.slice(0, 3).map(([k, v]) => `${esc(facetName(S.by, k))} ${share(v / total)}`).join(" · ")}</span>`
    : "<span>Rien à répartir</span>");
}

function tagsFor(ls) {
  const ks = [S.by, "cat", "liq", "goal"].filter((k, i, a) => a.indexOf(k) === i && k !== "inst");
  return `<span class="tags">${ks.flatMap((k) => [...new Set(ls.map((l) => l[k]))].filter((v) => v != null).map((v) => `<span class="tag${k === S.by ? " cur" : ""}" title="${FACET[k].label}">${facetIc(k, v)}${esc(facetName(k, v))}</span>`)).join("")}</span>`;
}

const rowId = (key) => `row-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
const accLabel = (l) => (l.inst === l.accName ? l.accName : `${l.inst} · ${l.accName}`);

// gain et rendement d'une ligne du détail : le serveur les donne par compte, par actif, par ligne
function statsFor(view, ls) {
  const perf = current.perf;
  if (!perf) return null;
  const f = ls[0];
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
  const yearAgo = iso(new Date(day(asOf) - 365 * 864e5));
  const ids = selIds(current.sel);
  const ctx = {
    S, n, per: per(), perf, src: current.src, all: current.all, sel: current.sel, pts, asOf,
    year: current.sel.length && S.tab === "rev" ? store.use(perfPath(yearAgo, "month", ids)) : null,
    kpis: S.tab === "rev" || S.tab === "traj" ? store.use(`/finance/kpis?month=${store.today}`) : null,
    months: S.tab === "traj" ? store.use(`/finance/budget/months?month=${shiftMonth(store.today, -1)}&months=12`) : null,
    look: S.tab === "risk" ? store.use("/finance/lookthrough?dimension=currency") : null,
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
  const groups = {};
  for (const l of sel) {
    const key = S.view === "acc" ? `a:${l.acc}` : `s:${l.asset}`;
    (groups[key] = groups[key] || []).push(l);
  }
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
    return `<div id="${rowId(r.key)}"><button class="row" type="button" data-a="w-row" data-v="${esc(r.key)}" aria-expanded="${open}">
      ${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}<span class="chev" aria-hidden="true">›</span></span><span class="row-sub">${r.sub}</span>${tagsFor(r.ls)}${r.partial ? `<span class="partial">${r.partial}</span>` : ""}</span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta">${rowDelta(r, items)}</span><span class="row-delta faint">${r.debt ? "" : total > 0 ? share(r.value / total) : "—"}</span></span>
    </button>${open ? `<div class="sub">${r.debt ? debtDetail(r.debt) : `${perfStrip(r)}${S.view === "acc" ? accountDetail(r, all) : assetDetail(r)}`}</div>` : ""}</div>`;
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
function perfStrip(r) {
  const c = r.c;
  if (!c || !current.items || current.items.length < 2) return "";
  const g = units(c.gain), twr = rate(c.twr), yr = rate(c.twr_yearly);
  if (r.cash) {
    return `<div class="strip"><div><span>Apports nets</span><b class="num">${signedMoney(units(c.net_flows))}</b></div><div><span>Intérêts</span><b class="num ${tone(g)}">${signedMoney(g)}</b></div><div><span>Rendement</span><b>—</b></div></div>
      <p class="pnote">Compte bancaire : pas de rendement en %, il suivrait surtout tes virements.</p>`;
  }
  return `<div class="strip"><div><span>Gain</span><b class="num ${tone(g)}">${signedMoney(g)}</b></div><div><span>Rendement</span><b class="num ${tone(twr)}">${ratePct(twr)}</b></div><div><span>Par an</span><b class="num ${tone(yr)}">${yr == null ? "—" : ratePct(yr)}</b></div></div>
    ${c.complete ? "" : '<p class="pnote">Des cours manquent sur la période : chiffres partiels.</p>'}
    <div class="sub-head"><span>D'où vient la valeur · ${per().label}</span></div>${bridge(c)}`;
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
  return `<div class="sub-head"><span>Composition du compte · objectif <b>${esc(facetName("goal", f.goal))}</b></span><button class="linkish" type="button" data-a="acc-edit" data-v="${esc(f.acc)}">Modifier</button></div>
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
  "w-tax": (v) => { S.tax = Number(v); remember(); store.notify(); },
  // une tuile qui filtre l'écran (la réserve : les liquidités)
  "w-only": (v) => {
    const i = v.indexOf("|");
    only(v.slice(0, i), v.slice(i + 1));
    remember();
    store.notify();
    announceSel();
    window.scrollTo({ top: 0 });
  },
  "w-period": (v) => { S.period = v; S.gran = per().def; S.scrub = null; remember(); store.notify(); },
  "w-gran": (v) => { S.gran = v; S.scrub = null; remember(); store.notify(); },
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
  "w-fold": (k) => {
    FOLD[k] = !FOLD[k];
    setPref("fold", FOLD);
    store.notify();
  },
};

