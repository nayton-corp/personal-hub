// Budget : reste à vivre et rythme du mois, projection et taux d'épargne ; une section
// Catégories (variables d'abord, les dépassements en tête, puis les fixes repliées) ; le
// diagramme de flux (revenus → usage → postes), toujours ouvert ; abonnements et tendance sur
// six mois, repliés sur une ligne de résumé. Les
// montants viennent de /finance/budget, /flows, /budget/months ; seul le rythme (part du mois
// écoulée) et la projection se calculent ici.
import { go, reveal } from "./shell.js";
import { MOIS, base, date, monthName } from "./format.js";
import { GROUP_LABEL, catLook, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { monthStartDay, shiftMonth, store } from "./store.js";
import {
  SHEETS, SH, amount, amount2, announce, closeSheet, esc, failure, fill, ibox, ic, money, n0, nf, openSheet, pf, pref,
  renderSheet, setPref, skel, toast,
} from "./ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const UNCAT = "a-categoriser";
const CADENCE = { weekly: "chaque semaine", monthly: "mensuel", quarterly: "trimestriel", yearly: "annuel" };
const OLDEST = 36; // mois en arrière au plus
const B = { sk: null, bgroup: null };

export const budgetPath = (month, period) => `/finance/budget?month=${month}&period=${period}`;
const flowsPath = () => `/finance/flows?month=${P.month}&period=${P.period}`;
const monthsPath = () => `/finance/budget/months?month=${P.month}&months=6`;
const recurringPath = "/finance/recurring";
const trendPath = (cat) => `/finance/trend?category=${encodeURIComponent(cat)}&months=6&month=${P.month}`;
const u = (m) => (m ? m.minor / 100 : 0);

// jours de la période : le mois budgétaire peut commencer un autre jour que le 1er
const daysIn = (b) => Math.round((Date.parse(`${b.end}T00:00:00Z`) - Date.parse(`${b.start}T00:00:00Z`)) / 864e5);

// chiffres d'une période : dépensé, budget, reste, rythme attendu, état, projection
export function model(b, current = b.month === store.today && b.period === "m") {
  const lines = b.lines.map((l) => ({ ...l, s: u(l.spent), t: l.target ? u(l.target) : null }));
  const T = b.budget ? u(b.budget) : null;
  // hors catégories suivies à l'année : elles ont leur propre jauge, depuis janvier
  const spent = u(b.budgeted_expenses || b.expenses);
  const pace = current ? (daysIn(b) - b.days_left) / daysIn(b) : null;
  const tf = lines.filter((l) => l.group === "fixed" && l.t).reduce((t, l) => t + l.t, 0);
  const tv = lines.filter((l) => l.group !== "fixed" && l.t).reduce((t, l) => t + l.t, 0);
  const expected = pace != null && tf + tv > 0 ? (tf + tv * pace) / (tf + tv) : null;
  const rest = T == null ? null : u(b.rest_to_live);
  const ratio = T ? spent / T : 0;
  let state;
  if (T == null) state = { k: "ok", short: "Sans budget", color: "var(--accent)", icon: "info", text: "Pas encore de budget : fixe une cible par catégorie pour suivre le reste à vivre." };
  else if (!current) {
    state = rest >= 0
      ? { k: "good", short: "Clos", color: "var(--accent)", icon: "check", text: `Période close avec ${n0(rest)} ${base()} d'avance sur le budget` }
      : { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Période close avec un dépassement de ${n0(-rest)} ${base()}` };
  } else if (rest < 0) state = { k: "bad", short: "Dépassé", color: "var(--neg)", icon: "alert", text: `Budget dépassé de ${n0(-rest)} ${base()}` };
  else if (expected != null && ratio > expected + 0.03) state = { k: "warn", short: "Au-dessus du rythme", color: "var(--s3)", icon: "alert", text: `Au-dessus du rythme : ${pf(ratio, 0)} % dépensés, ${pf(expected, 0)} % attendus à ce jour` };
  else state = { k: "good", short: "Dans le rythme", color: "var(--accent)", icon: "check", text: expected != null ? `Dans le rythme : ${pf(ratio, 0)} % dépensés, ${pf(expected, 0)} % attendus à ce jour` : `${pf(ratio, 0)} % du budget dépensé` };
  // fin de période : les fixes restants tombent, le reste suit son rythme actuel
  const projection = pace ? lines.filter((l) => !l.yearly).reduce((t, l) => t + (l.group === "fixed" ? Math.max(l.s, l.t || 0) : l.s / pace), 0) : null;
  return { lines, T, spent, rest, ratio, pace, expected, state, projection, current, daysLeft: b.days_left };
}

function catState(l, pace) {
  if (l.t == null) return { k: "ok", col: "var(--faint)", txt: "Hors budget" };
  const r = l.t ? l.s / l.t : 0;
  if (l.s > l.t) return { k: "bad", col: "var(--neg)", txt: `Dépassé de ${n0(l.s - l.t)}` };
  if (pace != null && l.group !== "fixed" && r > pace + 0.05) return { k: "warn", col: "var(--s3)", txt: `Reste ${n0(l.t - l.s)}, au-dessus du rythme` };
  if (l.group === "fixed" && l.s >= l.t - 0.5) return { k: "ok", col: "var(--pos)", txt: "Payé" };
  return { k: "ok", col: "var(--pos)", txt: `Reste ${n0(l.t - l.s)}` };
}

const shortMonth = (m) => MOIS[Number(m.slice(5, 7)) - 1];
// dates d'une période dont le mois ne commence pas le 1er : « 25 sept. – 24 oct. »
function spanLabel(b) {
  const last = new Date(Date.parse(`${b.end}T00:00:00Z`) - 864e5);
  const first = new Date(`${b.start}T00:00:00Z`);
  return `${first.getUTCDate()} ${MOIS[first.getUTCMonth()]} – ${last.getUTCDate()} ${MOIS[last.getUTCMonth()]}`;
}

function periodLabel(b) {
  if (P.period === "m") return monthName(P.month);
  const ms = b ? b.months : [shiftMonth(P.month, -3), shiftMonth(P.month, -1)];
  return `${shortMonth(ms[0])} – ${shortMonth(ms[ms.length - 1])} ${ms[ms.length - 1].slice(0, 4)}`;
}

// --- diagramme de flux ------------------------------------------------------------------------

function sankeyData(f) {
  const I = u(f.income);
  const g = Object.fromEntries(f.groups.map((x) => [x.group, x]));
  const F = u(g.fixed?.total), V = u(g.variable?.total), S = u(g.savings?.total);
  const out = F + V + S;
  const srcs = f.sources.filter((s) => u(s.total) > 0).map((s) => ({ id: `src:${s.category}`, name: s.name, v: u(s.total), c: catLook(s.category, "income").color, ic: catLook(s.category, "income").icon, col: 0 }))
    .sort((a, b) => b.v - a.v);
  if (out > I) srcs.push({ id: "src:deficit", name: "Réserves", v: out - I, c: "var(--neg)", ic: "wallet", col: 0, note: "Les sorties dépassent les revenus : la différence vient de tes réserves." });
  const tot = Math.max(I, out) || 1, R = Math.max(0, I - out), small = tot * 0.03;
  const kids = (key) => {
    const cs = (g[key]?.items || []).filter((i) => u(i.total) > 0).map((i) => ({
      id: `c:${i.category}`, cat: i.category, name: i.name, v: u(i.total), c: catLook(i.category, key).color, ic: catLook(i.category, key).icon,
      uncl: i.category === UNCAT, sav: key === "savings", group: key,
    }));
    cs.sort((x, y) => y.v - x.v);
    const big = cs.filter((c) => c.v >= small), sm = cs.filter((c) => c.v < small);
    if (sm.length > 1) big.push({ id: `c:autres-${key}`, name: key === "fixed" ? "Autres fixes" : key === "variable" ? "Autres variables" : "Autre épargne", v: sm.reduce((t, c) => t + c.v, 0), c: "var(--faint)", ic: "dots", others: sm });
    else big.push(...sm);
    return big;
  };
  const mids = [
    { id: "g:fixed", g: "fixed", name: "Fixes", v: F, c: "var(--s1)", ic: "home", kids: kids("fixed") },
    { id: "g:variable", g: "variable", name: "Variables", v: V, c: "var(--s3)", ic: "cart", kids: kids("variable") },
    { id: "g:savings", g: "savings", name: "Épargne", v: S, c: "var(--s2)", ic: "piggy", kids: kids("savings") },
  ].filter((m) => m.v > 0);
  if (R > 0) mids.push({ id: "g:rest", g: "rest", name: "Reste", v: R, c: "var(--faint)", ic: "wallet", kids: [] });
  for (const m of mids) {
    m.col = 1;
    for (const k of m.kids) { k.col = 2; k.parent = m.id; k.bar = m.c; }
  }
  return { srcs, mids, tot, I, R, out, S };
}

function sankeySvg(sd) {
  const W = 358, nw = 9, X = [0, 122, 232], padL = 10, padM = 12, padR = 12, H0 = 460;
  const right = sd.mids.flatMap((m) => m.kids), totR = right.reduce((t, k) => t + k.v, 0) || 1;
  const k = Math.min((H0 - padL * (sd.srcs.length - 1)) / sd.tot, (H0 - padM * (sd.mids.length - 1)) / sd.tot, (H0 - padR * Math.max(0, right.length - 1)) / totR);
  const place = (arr, pad) => {
    let y = 0;
    for (const n of arr) { n.h = Math.max(2, n.v * k); n.y = y; y += n.h + pad; }
    return y - pad;
  };
  const hL = place(sd.srcs, padL), hM = place(sd.mids, padM), hR = place(right, padR), H = Math.max(hL, hM, hR, 40) + 4;
  for (const [arr, h] of [[sd.srcs, hL], [sd.mids, hM], [right, hR]]) for (const n of arr) n.y += (H - h) / 2;
  const sel = B.sk, all = [...sd.srcs, ...sd.mids, ...right], selN = all.find((n) => n.id === sel);
  const band = (xa, ya0, ya1, xb, yb0, yb1) => {
    const xm = (xa + xb) / 2;
    return `M${xa},${ya0.toFixed(1)}C${xm},${ya0.toFixed(1)} ${xm},${yb0.toFixed(1)} ${xb},${yb0.toFixed(1)}L${xb},${yb1.toFixed(1)}C${xm},${yb1.toFixed(1)} ${xm},${ya1.toFixed(1)} ${xa},${ya1.toFixed(1)}Z`;
  };
  const cls = (on) => `sk-link${selN ? (on ? " on" : " off") : ""}`;
  // revenus et groupes sont deux piles du même total : chaque flux relie les tranches qui se
  // recouvrent, donc aucun flux n'en croise un autre (le salaire paie d'abord les fixes, etc.).
  // Chaque flux (et la barre de chaque poste) prend la couleur de son groupe, de la source aux postes.
  let links = "";
  const mOut = {}, feeds = new Set();
  let s0 = 0, m0 = 0, si = 0, mi = 0;
  while (si < sd.srcs.length && mi < sd.mids.length) {
    const s = sd.srcs[si], m = sd.mids[mi];
    const lo = Math.max(s0, m0), hi = Math.min(s0 + s.v, m0 + m.v);
    if (hi - lo > 1e-6) {
      feeds.add(`${s.id}|${m.id}`);
      const w = (hi - lo) * k, a0 = s.y + (lo - s0) * k, b0 = m.y + (lo - m0) * k;
      const on = !selN || sel === s.id || sel === m.id || selN.parent === m.id;
      links += `<path class="${cls(on)}" d="${band(X[0] + nw, a0, a0 + w, X[1], b0, b0 + w)}" data-css="fill:${m.c}"/>`;
    }
    if (s0 + s.v <= m0 + m.v) { s0 += s.v; si++; } else { m0 += m.v; mi++; }
  }
  for (const m of sd.mids) for (const kd of m.kids) {
    const w = kd.h, a0 = m.y + (mOut[m.id] || 0);
    mOut[m.id] = (mOut[m.id] || 0) + w;
    const on = !selN || sel === m.id || sel === kd.id || feeds.has(`${sel}|${m.id}`);
    links += `<path class="${cls(on)}" d="${band(X[1] + nw, a0, a0 + w, X[2], kd.y, kd.y + w)}" data-css="fill:${m.c}"/>`;
  }
  // libellés sans chevauchement : chaque colonne repousse vers le bas ce qui toucherait le précédent
  const labels = (arr, x, w) => {
    let prev = -99;
    return arr.map((n) => {
      const cy = Math.max(n.y + n.h / 2, prev + 25);
      prev = cy;
      const dim = selN && !(n.id === sel || n.parent === sel || selN.parent === n.id || feeds.has(`${sel}|${n.id}`) || feeds.has(`${n.id}|${sel}`) || feeds.has(`${sel}|${n.parent}`) || feeds.has(`${n.id}|${selN.parent}`));
      const pctI = sd.I ? ` · ${pf(n.v / sd.I, 0)} %` : "";
      return `<g class="sk-node${sel === n.id ? " sel" : ""}${dim ? " dim" : ""}" data-a="sk" data-v="${esc(n.id)}" tabindex="0" role="button" aria-pressed="${sel === n.id}" aria-label="${esc(n.name)}, ${n0(n.v)} ${base()}${sd.I ? `, ${pf(n.v / sd.I, 0)} % des revenus` : ""}">
        <rect class="sk-hit" x="${x - 4}" y="${(Math.min(n.y, cy - 14) - 2).toFixed(1)}" width="${w}" height="${(Math.max(n.h, 28) + 4).toFixed(1)}"/>
        <rect class="sk-bar" x="${x}" y="${n.y.toFixed(1)}" width="${nw}" height="${n.h.toFixed(1)}" rx="2" data-css="fill:${n.bar || n.c}"/>
        <text class="sk-name" x="${x + nw + 5}" y="${(cy - 2).toFixed(1)}">${esc(n.name)}</text>
        <text class="sk-val money" x="${x + nw + 5}" y="${(cy + 10).toFixed(1)}">${n0(n.v)}${n.col === 1 ? pctI : ""}</text></g>`;
    }).join("");
  };
  return `<svg class="sankey" viewBox="0 0 ${W} ${H.toFixed(0)}" role="group" aria-label="Diagramme de flux du budget : d'où vient l'argent et où il va">${links}${labels(sd.srcs, X[0], 112)}${labels(sd.mids, X[1], 104)}${labels(right, X[2], 126)}</svg>`;
}

function sankeyInfo(sd) {
  const all = [...sd.srcs, ...sd.mids, ...sd.mids.flatMap((m) => m.kids)], n = all.find((x) => x.id === B.sk);
  if (!n) return '<div class="skinfo"><span class="hint">Touche un bloc pour suivre son flux.</span></div>';
  const pct = sd.I ? `${pf(n.v / sd.I, 0)} % des revenus` : "";
  let sub = pct, btn = "";
  if (n.col === 1 && n.g !== "rest") {
    sub = `${pct} · ${n.kids.length} poste${n.kids.length > 1 ? "s" : ""}`;
    btn = `<button class="secondary" type="button" data-a="sk-list" data-v="${n.g}">${ic("list")}Voir le détail de ce groupe</button>`;
  }
  if (n.col === 1 && n.g === "rest") sub = `${pct} · ni dépensé ni épargné à ce jour`;
  if (n.cat && !n.uncl && !n.sav) btn = `<button class="secondary" type="button" data-a="cat" data-v="${esc(n.cat)}">${ic("chev")}Ouvrir ${esc(n.name)}</button>`;
  if (n.uncl) btn = `<button class="secondary" type="button" data-a="gotodo">${ic("help")}Classer dans le journal</button>`;
  if (n.others) sub = `${pct} · ${n.others.map((o) => esc(o.name)).join(", ")}`;
  if (n.sav) sub = `${pct} · versé sur la période`;
  if (n.note) sub = n.note;
  return `<div class="skinfo" role="status">
    <div class="ihead">${ibox(ic(n.ic), n.c === "var(--faint)" ? "var(--muted)" : n.c)}<span class="row-main"><span class="row-title">${esc(n.name)}</span><span class="row-sub">${sub}</span></span><span class="row-val num">${amount(n.v)}</span></div>
    <div class="acts">${btn}<button class="secondary" type="button" data-a="sk" data-v="" aria-label="Effacer la sélection">${ic("close")}</button></div></div>`;
}

// --- rendu ------------------------------------------------------------------------------------

export function render() {
  const be = store.use(budgetPath(P.month, P.period));
  const b = be.data;
  const fe = store.use(flowsPath());
  const me = store.use(monthsPath());
  const re = store.use(recurringPath);
  const lab = periodLabel(b);
  const oldest = shiftMonth(store.today, -OLDEST);
  fill($("budCtx"), `<div class="stepper" role="group" aria-label="Mois affiché">
      <button type="button" data-a="bm" data-v="-1" aria-label="Mois précédent" ${P.month <= oldest ? "disabled" : ""}>${ic("back")}</button>
      <b aria-live="polite">${esc(lab)}${b && monthStartDay() !== 1 ? `<small class="per-dates">${esc(spanLabel(b))}</small>` : ""}</b>
      <button type="button" data-a="bm" data-v="1" aria-label="Mois suivant" ${P.month >= store.today ? "disabled" : ""}>${ic("chev")}</button></div>
    <div class="seg small" role="group" aria-label="Période"><button type="button" data-a="bper" data-v="m" aria-pressed="${P.period === "m"}">Mois</button><button type="button" data-a="bper" data-v="q" aria-pressed="${P.period === "q"}" aria-label="Trois mois complets avant le mois choisi">3 mois</button></div>`);
  if (be.status === "error") return fill($("budBody"), `<div class="err-box" role="alert">Impossible de charger le budget : ${esc(be.error.message)}</div>`);
  if (!b) return fill($("budBody"), skel());
  const m = model(b);
  const st = m.state;
  let proj = "";
  if (m.projection != null && m.T != null) {
    const d = m.projection - m.T;
    proj = `<div class="proj">${ic("trend")}<span>Projection fin ${P.period === "m" ? monthName(P.month).split(" ")[0] : "de période"} : <b class="num">${amount(m.projection)}</b>, ${d > 0 ? `<span class="delta neg">${n0(d)} au-dessus</span>` : `<span class="delta pos">${n0(-d)} sous</span>`} le budget</span></div>`;
  }
  const hero = `<section class="card" aria-labelledby="t-bud">
      <div class="hero-label"><span id="t-bud">${m.T == null ? "Dépensé" : P.period === "m" ? "Reste à vivre" : "Reste sur 3 mois"}</span><span>${m.current ? `${m.daysLeft} jour${m.daysLeft > 1 ? "s" : ""} restant${m.daysLeft > 1 ? "s" : ""}` : "clos"}</span></div>
      <div class="hero-amount num${m.rest != null && m.rest < 0 ? " neg" : ""}"><span class="money">${nf(m.T == null ? m.spent : m.rest)}</span><small>${base()}</small></div>
      ${m.T == null ? "" : `<div class="hint">${amount(m.spent)} dépensés sur ${amount(m.T)} de budget</div>
      <div class="pbar" role="img" aria-label="${pf(m.ratio, 0)} % du budget dépensé${m.expected != null ? `, ${pf(m.expected, 0)} % attendus à ce jour` : ""}" data-css="--c:${st.color}"><i data-css="width:${Math.min(100, m.ratio * 100).toFixed(1)}%"></i>${m.expected != null ? `<span class="pace" data-css="left:${(m.expected * 100).toFixed(1)}%"></span>` : ""}</div>`}
      <div class="status ${st.k}">${ic(st.icon)}<span>${st.text}</span></div>
      ${fe.data ? savingsStrip(fe.data) : ""}
      ${proj}
    </section>`;
  // flux
  let flow = "";
  if (fe.data) {
    const sd = sankeyData(fe.data);
    if (B.sk && ![...sd.srcs, ...sd.mids, ...sd.mids.flatMap((x) => x.kids)].some((n) => n.id === B.sk)) B.sk = null;
    const spentF = sd.out - sd.S;
    flow = `<section class="card" aria-labelledby="t-flow">
      <div class="section-head"><h2 class="section-title" id="t-flow">Où va l'argent</h2></div>
      <p class="hint">Entré ${amount(sd.I)} · dépensé ${amount(spentF)} · épargné ${amount(sd.S)}</p>
      ${sd.tot > 1 ? `<div class="skcols" aria-hidden="true"><span>Revenus</span><span>Usage</span><span>Postes</span></div>${sankeySvg(sd)}${sankeyInfo(sd)}` : '<div class="empty">Aucun mouvement sur la période.</div>'}
    </section>`;
  } else if (fe.status === "error") flow = `<div class="err-box">Flux indisponible : ${esc(fe.error.message)}</div>`;
  fill($("budBody"), hero + categories(m) + flow + subscriptions(re) + trend(me) + '<div class="endspace"></div>');
}

// revenus, épargne et taux d'épargne de la période, sous le reste à vivre
function savingsStrip(f) {
  const I = u(f.income), S = u(f.groups.find((x) => x.group === "savings")?.total);
  return `<div class="strip three"><div><span>Revenus</span><b class="num">${money(I)}</b></div><div><span>Épargné</span><b class="num">${money(S)}</b></div><div><span>Taux d'épargne</span><b class="num">${I ? `${pf(S / I, 0)} %` : "—"}</b></div></div>`;
}

// en-tête d'une section repliable, avec sa ligne de résumé une fois repliée
function foldHead(id, title, open, sum) {
  return `<div class="section-head"><button class="fold-btn" type="button" data-a="bfold" data-v="${id}" aria-expanded="${open}" aria-controls="${id}-body"><h2 class="section-title" id="t-${id}">${title}</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
    ${open ? "" : `<button class="sec-sum" type="button" data-a="bfold" data-v="${id}" aria-label="Déplier ${title}"><span>${sum}</span></button>`}`;
}

// catégorie suivie à l'année : le cumul depuis janvier face à la cible annuelle
function yearState(c) {
  const y = c.yearly, done = u(y.spent), goal = y.target ? u(y.target) : null;
  return goal == null ? { k: "ok", col: "var(--faint)", txt: "Sans cible annuelle" }
    : done > goal ? { k: "bad", col: "var(--neg)", txt: `Dépassé de ${n0(done - goal)} sur l'année` }
    : { k: "ok", col: "var(--pos)", txt: `Reste ${n0(goal - done)} sur l'année` };
}

function yearRow(c) {
  const y = c.yearly, done = u(y.spent), goal = y.target ? u(y.target) : null;
  const r = goal ? done / goal : 0;
  const s = yearState(c);
  const month = c.s ? ` · ${n0(c.s)} ce mois` : "";
  return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(c.name)}, ${n0(done)}${goal != null ? ` sur ${n0(goal)}` : ""} ${base()} depuis janvier, ${s.txt}">
    ${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)} <span class="pill">par an</span></b><span class="t num">${money(done)}${goal != null ? ` / ${money(goal)}` : ""}</span></span>
    ${goal != null ? `<span class="pbar thin" data-css="--c:${s.col}"><i data-css="width:${Math.min(100, r * 100).toFixed(1)}%"></i></span>` : ""}
    <span class="crow-st ${s.k}">${s.txt}${month}</span></span></button>`;
}

// une ligne de catégorie : barre, trait du rythme, et l'état en mots (en pastille s'il dérape)
function catRow(c, pv) {
  if (c.yearly) return yearRow(c);
  const cp = c.group === "fixed" ? null : pv;
  const s = catState(c, cp), r = c.t ? c.s / c.t : 0;
  const tag = s.k === "bad" ? '<span class="pill bad">Dépassé</span>' : s.k === "warn" ? '<span class="pill warn">Au-dessus du rythme</span>' : "";
  return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(c.name)}, ${n0(c.s)}${c.t != null ? ` sur ${n0(c.t)}` : ""} ${base()}, ${s.txt}">
    ${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}${tag}</b><span class="t num">${money(c.s)}${c.t != null ? ` / ${money(c.t)}` : ""}</span></span>
    ${c.t != null ? `<span class="pbar thin" data-css="--c:${s.col}"><i data-css="width:${Math.min(100, r * 100).toFixed(1)}%"></i>${cp != null ? `<span class="pace" data-css="left:${(cp * 100).toFixed(1)}%"></span>` : ""}</span>` : ""}
    <span class="crow-st ${s.k}">${s.txt}</span></span></button>`;
}

// gravité pour le tri : dépassé, puis au-dessus du rythme, puis le reste par part consommée
const rank = (c, pv) => ({ bad: 2, warn: 1 })[catState(c, c.group === "fixed" ? null : pv).k] || 0;

function categories(m) {
  const pv = m.pace;
  const uncl = m.lines.find((l) => l.category === UNCAT);
  const sum2 = (cs) => [cs.filter((c) => !c.yearly).reduce((t, c) => t + c.s, 0), cs.reduce((t, c) => t + (c.t || 0), 0)];
  const pick = (gs) => m.lines.filter((l) => gs.includes(l.group) && l.category !== UNCAT)
    .sort((x, y) => rank(y, pv) - rank(x, pv) || (y.t ? y.s / y.t : 0) - (x.t ? x.s / x.t : 0) || y.s - x.s);
  if (B.bgroup === "savings" || B.bgroup === "rest") return savingsOrRest();
  const vars = B.bgroup === "fixed" ? [] : pick(["variable", "mixed"]);
  const fixed = B.bgroup === "variable" ? [] : pick(["fixed"]);
  const [vs, vt] = sum2(vars), [fs, ft] = sum2(fixed);
  const paid = fixed.filter((c) => c.t != null && c.s >= c.t - 0.5).length, due = fixed.filter((c) => c.t != null).length;
  const openFixed = B.bgroup === "fixed" || pref("fixedOpen", false);
  const nOver = m.lines.filter((l) => l.over).length;
  const head = B.bgroup
    ? `<button class="chip" type="button" data-a="bgroupx" aria-label="Retirer le filtre ${GROUP_LABEL[B.bgroup]}">${GROUP_LABEL[B.bgroup]}${ic("close")}</button>`
    : `<span class="hint num">${money(vs + fs)}${vt + ft ? ` / ${money(vt + ft)}` : ""}</span>`;
  const unclRow = uncl && B.bgroup !== "fixed"
    ? `<button class="crow" type="button" data-a="gotodo">${catMark(null)}<span><span class="crow-top"><b>Non classées</b><span class="t num">${amount(uncl.s)}</span></span><span class="crow-st warn">${uncl.count} écriture${uncl.count > 1 ? "s" : ""} à classer dans le journal</span></span></button>` : "";
  const varPart = vars.length ? `<div class="grp"><span>Variables</span><span class="num">${money(vs)}${vt ? ` / ${money(vt)}` : ""}</span></div>${vars.map((c) => catRow(c, pv)).join("")}` : "";
  const fixedPart = fixed.length ? `<button class="grp grp-btn" type="button" data-a="bfixed" aria-expanded="${openFixed}" aria-controls="fixed-body"><span>Fixes · <span class="num">${money(fs)}${ft ? ` / ${money(ft)}` : ""}</span></span>
      <span class="grp-st">${due ? `${paid === due ? ic("check") : ""}${paid} sur ${due} payée${due > 1 ? "s" : ""}` : ""}${ic("down", openFixed ? "up" : "")}</span></button>
      <div id="fixed-body">${openFixed ? fixed.map((c) => catRow(c, pv)).join("") : ""}</div>` : "";
  return `<section class="card" id="budCats" aria-labelledby="t-cats">
      <div class="section-head"><h2 class="section-title" id="t-cats">Catégories${nOver ? ` <span class="pill bad">${nOver} dépassée${nOver > 1 ? "s" : ""}</span>` : ""}</h2>${head}</div>
      ${unclRow}${varPart}${fixedPart || ""}${!vars.length && !fixed.length && !uncl ? '<div class="empty">Aucune dépense sur la période.</div>' : ""}
      ${B.bgroup ? "" : `<button class="secondary plan-btn" type="button" data-a="plan" aria-haspopup="dialog">${ic("wallet")}${m.T == null ? "Créer mon budget" : "Préparer le budget"}</button>`}
      ${pv != null && vars.length ? '<p class="hint">Le trait vertical marque où tu devrais en être aujourd\'hui. Les charges fixes sont dues en entier, elles n\'en ont pas.</p>' : ""}
    </section>`;
}

// le flux filtré sur l'épargne ou le reste : ses postes, sans budget
function savingsOrRest() {
  const head = `<div class="section-head"><h2 class="section-title" id="t-cats">${B.bgroup === "savings" ? "Épargne" : "Reste"}</h2><button class="chip" type="button" data-a="bgroupx" aria-label="Retirer le filtre">${B.bgroup === "savings" ? "Épargne" : "Reste"}${ic("close")}</button></div>`;
  if (B.bgroup === "rest") return `<section class="card" id="budCats" aria-labelledby="t-cats">${head}<div class="empty">Ni dépensé ni épargné pour l'instant.</div></section>`;
  const f = store.data(flowsPath());
  const items = f ? (f.groups.find((x) => x.group === "savings")?.items || []) : [];
  return `<section class="card" id="budCats" aria-labelledby="t-cats">${head}<div class="grp"><span>Épargne</span><span class="num">${amount(items.reduce((t, i) => t + u(i.total), 0))}</span></div>` +
    items.map((i) => `<div class="crow">${catMark(i.category, "savings")}<span><span class="crow-top"><b>${esc(i.name)}</b><span class="t num">${amount(u(i.total))}</span></span><span class="crow-st ok">${f.income.minor ? `${pf(u(i.total) / u(f.income), 0)} % des revenus` : ""}</span></span></div>`).join("") + "</section>";
}

function subscriptions(re) {
  const r = re.data;
  const items = r && r.items ? r.items.filter((x) => x.active) : [];
  if (!items.length) return "";
  const open = pref("subsOpen", false);
  const total = r.monthly_total.map((x) => `${n0(Math.abs(u(x)))} ${x.currency}`).join(" + ");
  const next = items.slice().sort((a, b) => (a.next_date || "").localeCompare(b.next_date || ""))[0];
  const ups = items.filter((s) => Math.abs(u(s.last_amount)) - Math.abs(u(s.amount)) > 0.009).length;
  const sum = `${items.length} abonnement${items.length > 1 ? "s" : ""} · ${esc(total)} par mois${next ? ` · prochain : ${esc(next.label)} le ${date(next.next_date)}` : ""}${ups ? ` · ${ups} en hausse` : ""}`;
  return `<section class="card${open ? "" : " folded"}" id="subs" aria-labelledby="t-subs">
      ${foldHead("subs", "Abonnements", open, sum)}
      ${open ? `<div class="sec-body" id="subs-body">${items.map((s) => {
        const up = Math.abs(u(s.last_amount)) - Math.abs(u(s.amount));
        return `<div class="kv">${ibox(ic("repeat"), "var(--s4)", "sm")}<span>${esc(s.label)}<span class="s">${CADENCE[s.cadence] || esc(s.cadence)} · prochain le ${date(s.next_date)}</span>${up > 0.009 ? ` <span class="pill warn">${ic("alert")}hausse +${amount2(up)}</span>` : ""}</span><b class="num">${amount2(Math.abs(u(s.last_amount)))}${s.amount.currency === base() ? "" : ` ${esc(s.amount.currency)}`}</b></div>`;
      }).join("")}<p class="hint">Paiements réguliers repérés dans le registre ; les prochaines échéances sont estimées.</p></div>` : ""}
    </section>`;
}

function trend(me) {
  const d = me.data;
  if (!d) return "";
  const ms = d.series.map((s) => ({ m: s.month, F: u(s.fixed), V: u(s.variable), S: u(s.savings) }));
  const mx = Math.max(1, ...ms.map((x) => x.F + x.V + x.S));
  const open = pref("trendOpen", false);
  const spend = ms.map((x) => x.F + x.V);
  const avg = spend.length > 1 ? spend.slice(0, -1).reduce((t, v) => t + v, 0) / (spend.length - 1) : null;
  const last = ms[ms.length - 1];
  const sum = last ? `Dépenses ${shortMonth(last.m)} ${n0(spend[spend.length - 1])}${avg != null ? `, moyenne des mois d'avant ${n0(avg)}` : ""} ${base()}` : "";
  if (!open) return `<section class="card folded" id="trend" aria-labelledby="t-trend">${foldHead("trend", "Tendance sur 6 mois", false, sum)}</section>`;
  return `<section class="card" id="trend" aria-labelledby="t-trend">
      ${foldHead("trend", "Tendance sur 6 mois", true, sum)}
      <p class="hint">Toucher un mois l'affiche.</p>
      <div class="months" role="group" aria-label="Choisir un mois">${ms.map((x) => {
        const t = x.F + x.V + x.S;
        return `<button class="mcol" type="button" data-a="month" data-v="${x.m}" aria-pressed="${P.period === "m" && P.month === x.m}" aria-label="${monthName(x.m)} : fixes ${n0(x.F)}, variables ${n0(x.V)}, épargne ${n0(x.S)}">
          <span class="bars" data-css="--h:${((t / mx) * 100).toFixed(0)}%"><i data-css="--f:${x.F};--c:var(--s1)"></i><i data-css="--f:${x.V};--c:var(--s3)"></i><i data-css="--f:${x.S};--c:var(--s2)"></i></span><span>${shortMonth(x.m)}</span></button>`;
      }).join("")}</div>
      <div class="legend"><span><i data-css="--c:var(--s1)"></i>Fixes</span><span><i data-css="--c:var(--s3)"></i>Variables</span><span><i data-css="--c:var(--s2)"></i>Épargne</span></div>
    </section>`;
}

// --- panneau d'une catégorie ------------------------------------------------------------------

SHEETS.cat = (id, sh) => {
  const b = store.data(budgetPath(P.month, P.period));
  const cats = store.data("/finance/categories");
  const c = cats ? cats.items.find((x) => x.id === id) : null;
  const l = b ? b.lines.find((x) => x.category === id) : null;
  if (!c && !l) return { title: "Catégorie", body: skel("block") };
  const name = c ? c.name : l.name, group = c ? c.group : l.group;
  const m = b ? model(b) : null;
  const line = m ? m.lines.find((x) => x.category === id) : null;
  const spent = line ? line.s : 0;
  const n = P.period === "q" ? 3 : 1;
  const year = line && line.yearly ? (line.yearly.target ? u(line.yearly.target) : null) : null;
  const target = line && line.yearly ? (year != null ? year / 12 : null) : line && line.t != null ? line.t / n : null; // cible mensuelle
  if (sh.cad == null) sh.cad = line && line.yearly ? "year" : "month";
  if (sh.tmp == null) sh.tmp = sh.cad === "year" ? Math.round(year || 0) : target != null ? Math.round(target) : 0;
  const was = line && line.yearly ? "year" : "month";
  const shown = was === "year" ? Math.round(year ?? -1) : Math.round(target ?? -1);
  const s = line ? (line.yearly ? yearState(line) : catState(line, group === "fixed" ? null : m.pace)) : { k: "ok", txt: "Aucune dépense" };
  const te = store.use(trendPath(id));
  let hist = skel("block");
  if (te.data) {
    const pts = te.data.series.map((x) => ({ m: x.month, v: Math.abs(u(x.total)) }));
    const mx = Math.max(1, ...pts.map((p) => p.v), target || 0) * 1.1;
    const look = catLook(id, group);
    hist = `<div class="mini-months" role="img" aria-label="${pts.map((p) => `${monthName(p.m).split(" ")[0]} ${n0(p.v)}`).join(", ")}${target != null ? `, cible ${n0(target)}` : ""}">
      ${target != null ? `<span class="tline" data-css="--b:${(18 + (target / mx) * 72).toFixed(0)}px"></span>` : ""}
      ${pts.map((p) => `<div><i class="${p.m === P.month ? "" : "past"}" data-css="--h:${((p.v / mx) * 72).toFixed(0)}px;--c:${target != null && p.v > target ? "var(--neg)" : look.color}"></i><span>${shortMonth(p.m)}</span></div>`).join("")}</div>
      ${target != null ? '<p class="hint">Pointillés : la cible mensuelle.</p>' : ""}`;
  }
  const budgetable = group === "fixed" || group === "variable";
  const changed = budgetable && sh.tmp > 0 && (sh.tmp !== shown || sh.cad !== was);
  const per = sh.cad === "year" ? "annuelle" : "mensuelle";
  return {
    title: `${catMark(id, group)}<span>${esc(name)}</span>`,
    body: `<div class="sheet-big num">${amount(spent)}${line && line.t != null ? ` <small>sur ${amount(line.t)}</small>` : ""}</div>
      <span class="crow-st ${s.k}">${esc(s.txt)} · ${esc(periodLabel(b))}</span>
      <h3>Six derniers mois</h3>${hist}
      ${budgetable ? `<h3>Cible ${per}</h3>
      <div class="seg cad-seg" role="group" aria-label="Suivi">${[["month", "Par mois"], ["year", "Par an"]].map(([k, l]) => `<button type="button" data-a="tcad" data-v="${k}" aria-pressed="${sh.cad === k}">${l}</button>`).join("")}</div>
      <div class="target"><button type="button" data-a="tstep" data-v="-10" aria-label="Diminuer de 10">−</button><input id="t-input" inputmode="numeric" value="${sh.tmp || ""}" aria-label="Cible ${per} en ${base()}" placeholder="aucune"><button type="button" data-a="tstep" data-v="10" aria-label="Augmenter de 10">+</button></div>
      ${sh.cad === "year" ? `<p class="hint">Pour les dépenses par à-coups (vacances, entretien) : comparée au cumul depuis janvier, sans peser sur le reste à vivre du mois.${line && line.yearly ? ` Dépensé depuis janvier : ${n0(u(line.yearly.spent))} ${base()}.` : ""}</p>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}` : '<p class="hint">Les cibles portent sur les dépenses fixes et variables.</p>'}
      ${line && line.count ? `<div class="stack-v"><button class="secondary" type="button" data-a="cat-tx" data-v="${esc(id)}">${ic("list")}${line.count > 1 ? `Voir les ${line.count} écritures` : "Voir l'écriture"}</button></div>` : ""}`,
    foot: budgetable ? `<button class="primary" type="button" data-a="target-save" ${changed && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer la cible avec Face ID"}</button>` : "",
  };
};

// --- préparer le budget : une cible par catégorie de dépense, proposée d'après les 3 derniers mois

const CATS = "/finance/categories";
const roundUp = (v) => (v > 0 ? Math.ceil(v / 10) * 10 : 0);

function planData() {
  const cur = store.data(budgetPath(store.today, "m")), past = store.data(budgetPath(store.today, "q")), cats = store.data(CATS);
  if (!cur || !past || !cats) return null;
  // une catégorie suivie à l'année se règle en montant annuel
  const year = new Set(cur.lines.filter((l) => l.yearly).map((l) => l.category));
  const now = Object.fromEntries(cur.lines.map((l) => [l.category, l.yearly ? (l.yearly.target ? u(l.yearly.target) : null) : l.target ? u(l.target) : null]));
  const avg = Object.fromEntries(past.lines.map((l) => [l.category, (u(l.spent) / past.months.length) * (year.has(l.category) ? 12 : 1)]));
  const rows = cats.items.filter((c) => c.active && (c.group === "fixed" || c.group === "variable"))
    .map((c) => ({ id: c.id, name: c.name, group: c.group, now: now[c.id] ?? null, avg: avg[c.id] || 0, year: year.has(c.id) }))
    .sort((a, b) => (a.group === b.group ? 0 : a.group === "fixed" ? -1 : 1) || b.avg - a.avg || a.name.localeCompare(b.name, "fr"));
  return { rows, income: u(past.income) / past.months.length, months: past.months };
}

const planChanges = (d, tmp) => d.rows.filter((r) => tmp[r.id] != null && tmp[r.id] !== (r.now ?? 0) && !(r.now == null && tmp[r.id] === 0));

SHEETS.plan = (_arg, sh) => {
  const d = planData();
  if (!d) return { title: "Préparer le budget", body: skel("block") };
  if (!sh.tmp) sh.tmp = Object.fromEntries(d.rows.map((r) => [r.id, r.now ?? roundUp(r.avg)]));
  const total = d.rows.reduce((t, r) => t + (sh.tmp[r.id] || 0) / (r.year ? 12 : 1), 0);
  const ch = planChanges(d, sh.tmp);
  const from = `${shortMonth(d.months[0])} – ${shortMonth(d.months[d.months.length - 1])}`;
  let g = null;
  const rows = d.rows.map((r) => {
    const head = r.group !== g ? `<div class="grp"><span>${GROUP_LABEL[r.group]}</span></div>` : "";
    g = r.group;
    const v = sh.tmp[r.id];
    return `${head}<div class="plan-row">${catMark(r.id, r.group, "sm")}
      <label for="plan-${esc(r.id)}"><b>${esc(r.name)}${r.year ? ' <span class="pill">par an</span>' : ""}</b><small>${r.avg ? `moyenne ${n0(r.avg)}` : "rien dépensé"}${r.now != null ? ` · cible ${n0(r.now)}` : ""}</small></label>
      <input id="plan-${esc(r.id)}" data-plan="${esc(r.id)}" inputmode="numeric" value="${v ? v : ""}" placeholder="—" aria-label="Cible ${r.year ? "annuelle" : "mensuelle"} ${esc(r.name)} en ${base()}"></div>`;
  }).join("");
  return {
    title: "Préparer le budget",
    body: `<p class="hint">Une cible par mois et par catégorie, proposée d'après ta moyenne des derniers mois (${esc(from)}) et arrondie à la dizaine. Laisse vide ce que tu ne veux pas suivre.</p>
      <div class="plan-sum"><span>Revenus<b class="num">${amount(d.income)}</b></span><span>Budget<b class="num">${amount(total)}</b></span><span>Reste<b class="num${d.income - total < 0 ? " neg" : ""}">${amount(d.income - total)}</b></span></div>
      ${rows}${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="plan-save" ${ch.length && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : ch.length ? `Enregistrer ${ch.length} cible${ch.length > 1 ? "s" : ""} avec Face ID` : "Aucun changement"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  const id = e.target.dataset && e.target.dataset.plan;
  if (!id || SH.kind !== "plan" || !SH.tmp) return;
  const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
  SH.tmp[id] = Number.isNaN(n) ? 0 : n;
  renderSheet();
});

document.addEventListener("input", (e) => {
  if (e.target.id !== "t-input" || SH.kind !== "cat") return;
  const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
  SH.tmp = Number.isNaN(n) ? 0 : n;
  renderSheet();
});

function setMonth(month) {
  if (month > store.today || month < shiftMonth(store.today, -OLDEST)) return;
  B.sk = null;
  store.set({ month });
  announce(P.period === "m" ? monthName(month) : periodLabel(null));
}

export const actions = {
  cat: (id) => {
    if (P.tab !== "budget") {
      store.set({ month: store.today, period: "m" });
      go("budget");
    }
    store.use("/finance/categories");
    openSheet("cat", id);
  },
  bm: (v) => setMonth(shiftMonth(P.month, Number(v))),
  bper: (v) => {
    B.sk = null;
    store.set({ period: v });
  },
  month: (v) => {
    B.sk = null;
    store.set({ month: v, period: "m" });
    window.scrollTo({ top: 0, behavior: "smooth" });
    announce(monthName(v));
  },
  sk: (v) => {
    B.sk = !v || B.sk === v ? null : v;
    store.notify();
  },
  "sk-list": (g) => {
    B.bgroup = g;
    store.notify();
    requestAnimationFrame(() => reveal($("budCats")));
  },
  bgroupx: () => {
    B.bgroup = null;
    store.notify();
  },
  bfold: (k) => {
    const key = `${k}Open`;
    setPref(key, !pref(key, false));
    store.notify();
  },
  bfixed: () => {
    setPref("fixedOpen", !pref("fixedOpen", false));
    store.notify();
  },
  subs: () => {
    setPref("subsOpen", true);
    store.set({ month: store.today, period: "m" });
    go("budget");
    requestAnimationFrame(() => requestAnimationFrame(() => reveal($("subs"))));
  },
  tcad: (k) => {
    if (SH.cad === k) return;
    // la même enveloppe, exprimée par an ou par mois
    SH.tmp = k === "year" ? (SH.tmp || 0) * 12 : Math.round((SH.tmp || 0) / 12);
    SH.cad = k;
    renderSheet();
  },
  tstep: (v) => {
    SH.tmp = Math.max(0, (SH.tmp || 0) + Number(v));
    renderSheet();
  },
  plan: () => {
    for (const p of [budgetPath(store.today, "m"), budgetPath(store.today, "q"), CATS]) store.use(p);
    openSheet("plan");
  },
  "plan-save": async () => {
    const d = planData();
    if (!d) return;
    const ch = planChanges(d, SH.tmp);
    if (!ch.length) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const items = ch.map((r) => ["set_budget", { category_id: r.id, monthly_minor: Math.round((SH.tmp[r.id] * 100) / (r.year ? 12 : 1)), valid_from: `${store.today}-01` }]);
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(`${ch.length} cible${ch.length > 1 ? "s" : ""} enregistrée${ch.length > 1 ? "s" : ""}`);
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "target-save": async () => {
    const id = SH.arg, value = SH.tmp, yearly = SH.cad === "year";
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const monthly = Math.round((value * 100) / (yearly ? 12 : 1));
      const [text, bad] = outcome(await proposeAndApprove([["set_budget", { category_id: id, monthly_minor: monthly, cadence: yearly ? "year" : "month" }]]));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(`Cible enregistrée : ${n0(value)} ${base()} par ${yearly ? "an" : "mois"}`);
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "cat-tx": (id) => {
    closeSheet(true);
    const months = P.period === "m" ? [P.month] : (store.data(budgetPath(P.month, P.period))?.months || [P.month]);
    store.set({ tx: "all", q: "", txcat: { id, from: months[0], to: months[months.length - 1] } });
    go("journal", { top: true });
  },
};

