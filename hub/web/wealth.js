// Patrimoine : une sélection (filtres par catégorie, disponibilité, objectif, institution) pilote
// tout l'écran : total et courbe, répartition, puis le détail par compte ou par actif, chacun
// dépliable et relié à l'autre. Les lignes viennent de /finance/accounts et /finance/holdings ;
// la courbe, de la valeur de chaque compte dans /finance/networth/history.
import { reveal } from "./finance.js";
import { MOIS, MOIS_L, base, date } from "./format.js";
import { CCY_NAME, FACET, FACETS, assetMark, facetColor, facetIc, facetMark, facetName, setInstitutions } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "./store.js";
import {
  SHEETS, SH, amount, announce, closeSheet, esc, failure, fill, ibox, ic, money, n0, n2, openSheet, pctOnly, pf, pref,
  qty, renderSheet, setPref, sgn, share, toast,
} from "./ui.js";

const $ = (id) => document.getElementById(id);
const paths = { accounts: "/finance/accounts", holdings: "/finance/holdings", history: "/finance/networth/history", fresh: "/finance/freshness" };
const KIND_LABEL = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };
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
const SORTS = [{ k: "val", label: "Valeur" }, { k: "chg", label: "Variation" }, { k: "az", label: "Nom" }];
const MAX_POINTS = 400;
const W = 340, H = 170, L = 2, R = 2, T = 10, BOT = 22;

const saved = pref("wealth", {});
const S = {
  filters: { cat: new Set(), liq: new Set(), goal: new Set(), inst: new Set() },
  by: BY.includes(saved.by) ? saved.by : "cat",
  period: PERIODS.some((p) => p.k === saved.period) ? saved.period : "1A",
  gran: GRAN[saved.gran] ? saved.gran : "S",
  mode: saved.mode === "perf" ? "perf" : "val",
  view: saved.view === "asset" ? "asset" : "acc",
  sort: SORTS.some((s) => s.k === saved.sort) ? saved.sort : "val",
  open: new Set(),
  scrub: null,
};
const FOLD = { evo: false, alloc: false, ...pref("fold", {}) };
let pts = []; // points de la courbe affichée

function remember() {
  const { by, period, gran, mode, view, sort } = S;
  setPref("wealth", { by, period, gran, mode, view, sort });
}

// --- lignes : un actif dans un compte ---------------------------------------------------------

function lastValues() {
  const h = store.data(paths.history);
  const last = h && h.items.length ? h.items[h.items.length - 1] : null;
  return last ? last.by_account : null;
}

let cache = { key: null, lines: [] };
function lines() {
  const acc = store.data(paths.accounts), hold = store.data(paths.holdings), byAcc = lastValues();
  if (!acc || !hold || !byAcc) return null;
  const key = [acc, hold, byAcc];
  if (cache.key && cache.key.every((x, i) => x === key[i])) return cache.lines;
  setInstitutions(acc.items.map((a) => a.institution));
  const out = [];
  for (const a of acc.items) {
    const total = byAcc[a.id] ? byAcc[a.id].minor / 100 : 0;
    const own = hold.items.filter((p) => p.account_id === a.id);
    const meta = { acc: a.id, accName: a.name, inst: a.institution, liq: a.availability, goal: a.goal, kind: a.kind };
    let held = 0;
    for (const p of own) {
      const v = p.value.minor / 100;
      held += v;
      const crypto = p.kind === "crypto";
      out.push({ ...meta, asset: `isin:${p.isin}`, name: p.name, symbol: crypto ? p.isin : null, cat: crypto ? "crypto" : "funds", qty: p.quantity, unit: crypto ? p.isin : "parts", value: v, price: p.price, priceCcy: p.price_currency, priceDate: p.price_date });
    }
    const rest = total - held;
    if (!own.length || Math.abs(rest) >= 1) {
      // sans positions : le solde, dans la devise du compte ; avec : le reste, déjà converti
      const ccy = own.length ? base() : a.balance.currency;
      const q = own.length ? rest : a.balance.minor / 100;
      out.push({ ...meta, asset: `ccy:${ccy}`, name: CCY_NAME[ccy] || ccy, symbol: ccy, cat: a.kind === "crypto" && !own.length ? "crypto" : "cash", qty: q, unit: ccy, value: own.length ? rest : total });
    }
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

// part de chaque compte que porte un groupe de lignes, pour reporter la sélection sur la
// valeur historique des comptes (la composition d'un compte est supposée stable)
function fractions(all, part) {
  const out = {};
  const accs = new Set(part.map((l) => l.acc));
  for (const id of accs) {
    const mine = all.filter((l) => l.acc === id), tot = sum(mine), sel = part.filter((l) => l.acc === id);
    out[id] = Math.abs(tot) > 0.005 ? sum(sel) / tot : sel.length / mine.length;
  }
  return out;
}

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

function seriesSource(h) {
  const start = startDate(h);
  if (S.gran === "M") {
    const i = h.items.findIndex((x) => x.on_date > start);
    return { items: h.items.slice(Math.max(0, (i < 0 ? h.items.length : i) - 1)), status: "ok" };
  }
  const e = store.use(`${paths.history}?from=${start}&step=${GRAN[S.gran].step}`);
  return { items: e.data ? e.data.items : null, status: e.status, error: e.error };
}

function valueAt(item, frac) {
  let t = 0;
  for (const id in frac) {
    const v = item.by_account[id];
    if (v) t += (v.minor / 100) * frac[id];
  }
  return t;
}

function change(items, frac) {
  if (!items || items.length < 2) return { v: 0, p: null };
  const a = valueAt(items[0], frac), b = valueAt(items[items.length - 1], frac);
  return { v: b - a, p: a > 0.5 ? b / a - 1 : null };
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

let current = null; // { all, sel, frac, items }

export function render() {
  const ae = store.use(paths.accounts), he = store.use(paths.holdings), hi = store.use(paths.history);
  store.use(paths.fresh);
  const err = [ae, he, hi].find((e) => e.status === "error");
  const all = lines();
  renderFilterbar();
  if (err || !all) {
    fill($("hero"), err ? `<div class="err-box" role="alert">Impossible de charger le patrimoine : ${esc(err.error.message)}</div>` : '<div class="loading">Chargement…</div>');
    for (const id of ["heroFoot", "list", "allocList", "stack", "allocSum"]) fill($(id), "");
    $("chart").replaceChildren();
    return;
  }
  const h = hi.data;
  const sel = all.filter((l) => match(l));
  const frac = fractions(all, sel);
  const src = h.items.length ? seriesSource(h) : { items: [], status: "ok" };
  current = { all, sel, frac, items: src.items, h, src };
  for (const k of ["evo", "alloc"]) {
    $(k).classList.toggle("folded", FOLD[k]);
    const b = $(k).querySelector(".fold-btn");
    if (b) b.setAttribute("aria-expanded", String(!FOLD[k]));
  }
  drawControls(h);
  drawChart();
  drawFoot(all, sel);
  drawAlloc(sel);
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
  fill($("modeSeg"), [["val", "Valeur"], ["perf", "Perf. %"]].map(([k, l]) => `<button type="button" data-a="w-mode" data-v="${k}" aria-pressed="${S.mode === k}">${l}</button>`).join(""));
  fill($("periods"), PERIODS.map((p) => `<button class="pchip" type="button" data-a="w-period" data-v="${p.k}" aria-pressed="${S.period === p.k}" aria-label="Période ${p.label}">${p.k}</button>`).join(""));
  const gs = h.items.length ? grans(h) : ["M"];
  if (!gs.includes(S.gran)) S.gran = gs.includes(per().def) ? per().def : gs[gs.length - 1];
  $("granSeg").hidden = gs.length < 2;
  fill($("granSeg"), gs.map((g) => `<button type="button" data-a="w-gran" data-v="${g}" aria-pressed="${S.gran === g}">${GRAN[g].label}</button>`).join(""));
}

function heroTop(scrubbed) {
  const { sel, frac } = current;
  const n = activeCount();
  const scrub = scrubbed != null;
  const first = pts[0], last = pts[pts.length - 1];
  const v = scrub ? pts[scrubbed].v : sum(sel);
  const baseV = first ? first.v : 0;
  const dv = scrub ? pts[scrubbed].v - baseV : last ? last.v - baseV : 0;
  const dp = baseV > 0.5 ? (scrub ? pts[scrubbed].v : last.v) / baseV - 1 : null;
  void frac;
  fill($("hero"), `
    <div class="hero-label">${scrub ? `<span class="scrub-date">${fmtDate(pts[scrubbed].d, true)}</span>` : `<span>${n ? "Sélection filtrée" : "Patrimoine total"}</span>`}</div>
    <div class="hero-amount num"><span class="money">${n0(v)}</span><small>${base()}</small></div>
    <div class="hero-delta">${pts.length > 1 ? signed2(dv, dp) : ""}<span class="period-link">${scrub ? `depuis le ${fmtDate(first.d, true)}` : pts.length > 1 ? per().label : ""}</span></div>`);
  fill($("miniTotal"), `${n ? "Sélection · " : ""}${money(sum(sel))} ${base()}`);
}

const signed2 = (v, p) => `<span class="delta ${v >= 0 ? "pos" : "neg"} num"><span class="money">${sgn(v)}${n0(v)}</span> ${base()}${p == null ? "" : ` · ${sgn(p)}${pf(Math.abs(p))} %`}</span>`;

function drawChart() {
  if (!current) return;
  const { sel, frac, items, src } = current;
  const svg = $("chart");
  const est = $("estimate");
  pts = (items || []).map((it) => ({ d: it.on_date, v: valueAt(it, frac) }));
  const partial = Object.values(frac).some((f) => f > 0.001 && f < 0.999);
  est.hidden = !partial;
  est.textContent = partial ? "Courbe estimée : une partie des comptes filtrés est reportée selon sa composition actuelle." : "";
  if (S.scrub != null && S.scrub >= pts.length) S.scrub = null;
  heroTop(S.scrub);
  if (src && src.status === "error") return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Courbe indisponible : ${esc(src.error.message)}</text>`);
  if (!items) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Chargement…</text>`);
  if (!sel.length) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Aucune donnée pour cette sélection</text>`);
  if (pts.length < 2) return fill(svg, `<text x="${W / 2}" y="85" text-anchor="middle">Courbe en construction : un point par fin de mois</text>`);
  const b0 = pts.find((p) => p.v > 0.5)?.v || 0;
  const ys = pts.map((p) => (S.mode === "val" ? p.v : b0 ? p.v / b0 - 1 : 0));
  let mn = Math.min(...ys), mx = Math.max(...ys);
  if (S.mode === "perf") { mn = Math.min(mn, 0); mx = Math.max(mx, 0); }
  const pad = (mx - mn) * 0.08 || Math.abs(mx) * 0.05 || 1;
  mn -= pad; mx += pad;
  const X = (i) => L + (W - L - R) * (i / (pts.length - 1)), Y = (v) => T + (H - T - BOT) * (1 - (v - mn) / (mx - mn));
  const line = ys.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const area = `${line}L${X(ys.length - 1).toFixed(1)},${H - BOT}L${X(0).toFixed(1)},${H - BOT}Z`;
  const zero = S.mode === "perf" ? `<line class="zero" x1="${L}" x2="${W - R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/>` : "";
  const si = S.scrub == null ? ys.length - 1 : S.scrub;
  const cx = X(si), cy = Y(ys[si]);
  fill(svg, `<defs><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop class="g0" offset="0"/><stop class="g1" offset="1"/></linearGradient></defs>
    ${zero}<path class="area" d="${area}"/><path class="line" d="${line}"/>
    <text x="${L}" y="${H - 6}">${fmtDate(pts[0].d)}</text><text x="${W - R}" y="${H - 6}" text-anchor="end">${fmtDate(pts[pts.length - 1].d)}</text>
    ${S.scrub != null ? `<line class="cursor" x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${T}" y2="${H - BOT}"/>` : ""}
    <circle class="dot" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5"/>`);
}

function drawFoot(all, sel) {
  const n = activeCount();
  const total = sum(sel), whole = sum(all);
  const nacc = new Set(sel.map((l) => l.acc)).size;
  const f = store.data(paths.fresh);
  const last = f ? f.items.map((x) => x.last_import).filter(Boolean).sort().pop() : null;
  const stale = last && Date.now() - Date.parse(last) > 3 * 864e5;
  fill($("heroFoot"), `
    ${n && whole > 0 ? `<div class="share"><div class="sharebar"><i data-css="width:${Math.max(0, Math.min(100, (total / whole) * 100)).toFixed(1)}%"></i></div>${share(total / whole)} de ton patrimoine (${amount(whole)})</div>` : ""}
    <div class="hero-foot"><div class="fresh${stale ? " stale" : ""}"><i></i>${last ? `Mis à jour le ${date(last.slice(0, 10))}` : "Pas encore d'import"} · ${nacc} compte${nacc > 1 ? "s" : ""}</div>
    <button class="graph-toggle" type="button" data-a="w-fold" data-v="evo" aria-expanded="${!FOLD.evo}" aria-controls="evoBody">${FOLD.evo ? "Afficher la courbe" : "Masquer la courbe"}<svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>`);
}

function drawAlloc(sel) {
  fill($("bySeg"), BY.map((k) => `<button type="button" data-a="w-by" data-v="${k}" aria-pressed="${S.by === k}">${FACET[k].label}</button>`).join(""));
  const total = sum(sel), g = {};
  for (const l of sel) g[l[S.by]] = (g[l[S.by]] || 0) + l.value;
  const rows = Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => b[1] - a[1]);
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
  return `<span class="tags">${ks.flatMap((k) => [...new Set(ls.map((l) => l[k]))].map((v) => `<span class="tag${k === S.by ? " cur" : ""}" title="${FACET[k].label}">${facetIc(k, v)}${esc(facetName(k, v))}</span>`)).join("")}</span>`;
}

const rowId = (key) => `row-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
const accLabel = (l) => (l.inst === l.accName ? l.accName : `${l.inst} · ${l.accName}`);

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
    const c = change(items, fractions(all, ls));
    const f = ls[0];
    if (S.view === "acc") {
      const totalLines = all.filter((l) => l.acc === f.acc).length;
      return { key, ls, title: f.accName, sub: `${esc(f.inst)} · ${KIND_LABEL[f.kind] || ""}`, mark: facetMark("inst", f.inst, ""), value: sum(ls), c,
        partial: ls.length < totalLines ? `${ls.length} ligne${ls.length > 1 ? "s" : ""} sur ${totalLines} selon les filtres` : "" };
    }
    const q = ls.reduce((t, l) => t + Number(l.qty), 0);
    const where = ls.length > 1 ? `dans ${ls.length} comptes` : esc(accLabel(f));
    return { key, ls, title: f.name, sub: `<span class="money">${qty(q)}</span> ${esc(f.unit)} · ${where}`, mark: assetMark(f), value: sum(ls), c };
  });
  rows.sort(S.sort === "val" ? (a, b) => b.value - a.value : S.sort === "chg" ? (a, b) => (b.c.p ?? 9) - (a.c.p ?? 9) : (a, b) => a.title.localeCompare(b.title, "fr"));
  rows = rows.filter((r) => Math.abs(r.value) >= 0.5 || S.view === "acc");
  $("listCount").textContent = `${rows.length} ${S.view === "acc" ? "compte" : "actif"}${rows.length > 1 ? "s" : ""}`;
  if (!rows.length) {
    fill($("list"), '<div class="empty">Aucun élément ne correspond à ces filtres.<br><button type="button" data-a="w-clear">Effacer les filtres</button></div>');
    return;
  }
  const total = sum(sel);
  fill($("list"), rows.map((r) => {
    const open = S.open.has(r.key);
    return `<div id="${rowId(r.key)}"><button class="row" type="button" data-a="w-row" data-v="${esc(r.key)}" aria-expanded="${open}">
      ${r.mark}
      <span class="row-main"><span class="row-title">${esc(r.title)}<span class="chev" aria-hidden="true">›</span></span><span class="row-sub">${r.sub}</span>${tagsFor(r.ls)}${r.partial ? `<span class="partial">${r.partial}</span>` : ""}</span>
      <span class="row-num"><span class="row-val num">${amount(r.value)}</span><span class="row-delta">${items && items.length > 1 ? pctOnly(r.c.p) : ""} <span class="faint">· ${total > 0 ? share(r.value / total) : "—"}</span></span></span>
    </button>${open ? `<div class="sub">${S.view === "acc" ? accountDetail(r, all) : assetDetail(r)}</div>` : ""}</div>`;
  }).join(""));
}

function unitPrice(l) {
  if (l.asset.startsWith("ccy:")) return l.unit === base() ? "" : ` · cours ${(Math.abs(l.value / Number(l.qty)) || 0).toFixed(3).replace(".", ",")}`;
  return l.price ? ` × <span class="money">${n2(Number(l.price))}</span> ${esc(l.priceCcy || "")}` : " · sans cours";
}

function accountDetail(r, all) {
  const ls = r.ls.slice().sort((a, b) => b.value - a.value), tot = sum(ls) || 1;
  const items = current.items;
  const f = ls[0];
  return `<div class="sub-head"><span>Composition du compte · objectif <b>${esc(facetName("goal", f.goal))}</b></span><button class="linkish" type="button" data-a="w-goal" data-v="${esc(f.acc)}">Changer</button></div>
    <div class="compo" aria-hidden="true">${ls.map((l) => `<i data-css="--f:${Math.max(0, l.value).toFixed(2)};--c:${facetColor("cat", l.cat)}"></i>`).join("")}</div>
    ${ls.map((l) => {
      const c = change(items, fractions(all, [l]));
      return `<button class="sub-row" type="button" data-a="w-jump" data-v="s:${esc(l.asset)}" aria-label="${esc(l.name)}, ${share(l.value / tot)} du compte. Voir cet actif dans la vue Actifs">
        ${assetMark(l, "sm")}
        <span class="row-main"><span class="row-title">${esc(l.name)}</span><span class="row-sub"><span class="money">${qty(l.qty)}</span> ${esc(l.unit)}${unitPrice(l)}</span></span>
        <span class="row-num"><span class="num sub-val">${amount(l.value)}</span><span class="sub-share">${share(l.value / tot)}${items && items.length > 1 ? ` · ${pctOnly(c.p)}` : ""}</span></span>
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

SHEETS.goal = (id, sh) => {
  const acc = store.data(paths.accounts);
  const a = acc ? acc.items.find((x) => x.id === id) : null;
  if (!a) return null;
  if (sh.tmp == null) sh.tmp = a.goal;
  const f = FACET.goal;
  return {
    title: `${facetMark("inst", a.institution)}<span>${esc(a.name)}</span>`,
    body: `<p class="hint">L'objectif range ce compte dans le filtre « Objectif » et la répartition.${a.goal_set ? "" : " Pour l'instant, il est déduit du type de compte."}</p>
      <div class="catgrid" role="radiogroup" aria-label="Objectif">${f.values.map((v) => `<button type="button" role="radio" aria-checked="${sh.tmp === v}" data-a="w-goal-pick" data-v="${v}">${facetMark("goal", v, "xs")}${esc(f.names[v])}</button>`).join("")}</div>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="w-goal-save" ${(sh.tmp !== a.goal || !a.goal_set) && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
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
  "w-goal": (id) => openSheet("goal", id),
  "w-goal-pick": (v) => { SH.tmp = v; renderSheet(); },
  "w-goal-save": async () => {
    const id = SH.arg, goal = SH.tmp;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove([["set_account_goal", { account_id: id, goal }]]));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(`Objectif enregistré : ${facetName("goal", goal)}`);
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};

