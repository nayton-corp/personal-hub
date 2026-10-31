// Patrimoine : la courbe en SVG. Simple par défaut (la valeur, les dates en bas, quelques valeurs
// à droite) ; « Afficher » ajoute les apports, les avoirs et dettes, l'objectif, les événements,
// le plus haut et le plus bas. Une plage estimée est hachurée, la courbe y passe en pointillé.
// Le doigt lit une date ; la règle mesure entre deux dates. L'axe du temps est en jours : des
// cours espacés irrégulièrement restent à leur date.
import { MOIS, base } from "../../format.js";
import { S, day, longDate, shortDate } from "./wstate.js";
import { esc, n0, n2 } from "../../ui.js";
import { granLabel } from "./wmodel.js";

export const compact = (v) => {
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(".", ",")} M`;
  if (a >= 1e4) return `${s}${Math.round(a / 1e3)}k`;
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(1).replace(".", ",")}k`;
  return `${s}${Math.round(a)}`;
};
export const px = (v) => (Math.abs(v) >= 1000 ? n0(v) : n2(v));
export const pct = (x, d = 1) => (x == null || !Number.isFinite(x) ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(d).replace(".", ",")} %`);
export const sgnMoney = (v) => (Math.round(v) === 0 ? "0" : `${v > 0 ? "+" : "−"}${n0(v)}`);
export const EV = { in: "Versement", out: "Retrait", income: "Revenu" };
export const show = (k) => !S.hidden.has(k);

const R_GUT = 36, R_BIG = 46; // valeurs à droite, hors de la courbe
export const gutter = (big) => (big ? R_BIG : R_GUT);

function niceTicks(mn, mx, n) {
  const span = mx - mn || 1, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(mn / step) * step; v <= mx + 1e-9; v += step) out.push(v);
  return out;
}

// dates du bas : jour, lundi, quinzaine, mois, trimestre ou année selon la durée
function xTicks(t0, span, X, w) {
  const out = [];
  const pick = (d) => {
    const m = d.getUTCMonth(), dd = d.getUTCDate();
    if (span <= 12) return { l: `${dd} ${MOIS[m]}` };
    if (span <= 50) return d.getUTCDay() === 1 ? { l: `${dd} ${MOIS[m]}` } : null;
    if (span <= 130) return dd === 1 || dd === 15 ? { l: dd === 1 ? MOIS[m] : `15 ${MOIS[m]}` } : null;
    if (span <= 420) return dd === 1 && m % 2 === 0 ? { l: m === 0 ? String(d.getUTCFullYear()) : MOIS[m], strong: m === 0 } : null;
    if (span <= 1200) return dd === 1 && m % 3 === 0 ? { l: m === 0 ? String(d.getUTCFullYear()) : MOIS[m], strong: m === 0 } : null;
    if (span <= 3700) return dd === 1 && m === 0 ? { l: String(d.getUTCFullYear()), strong: true } : null;
    return dd === 1 && m === 0 && d.getUTCFullYear() % 2 === 0 ? { l: String(d.getUTCFullYear()), strong: true } : null;
  };
  let last = -1e9;
  for (let i = 0; i <= span; i++) {
    const t = pick(new Date(t0 + i * 864e5));
    if (!t) continue;
    const x = X(i / (span || 1));
    if (x - last < 40 || x < 12 || x > w - 12) continue;
    out.push({ x, ...t });
    last = x;
  }
  return out;
}

const Y_OF = { val: (p) => p.v, pos: (p) => p.v, gain: (p) => p.g, pct: (p) => p.r ?? 0, price: (p) => p.price };

// géométrie partagée par le dessin et le doigt
export function frame(m, w, big) {
  const pts = m.pts;
  const t0 = day(pts[0].d).getTime(), span = Math.max(1, Math.round((day(pts[pts.length - 1].d) - t0) / 864e5));
  const R = gutter(big);
  const X = (t) => (w - R) * t;
  const tOf = (d) => (day(d).getTime() - t0) / 864e5 / span;
  return { t0, span, R, X, xi: (k) => X(tOf(pts[k].d)), tOf };
}

// point le plus proche d'une fraction de largeur
export function nearest(m, t) {
  const pts = m.pts;
  const { t0, span } = frame(m, 100, false);
  const target = t0 + t * span * 864e5;
  let lo = 0, hi = pts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (day(pts[mid].d).getTime() < target) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && target - day(pts[lo - 1].d).getTime() < day(pts[lo].d).getTime() - target) lo -= 1;
  return lo;
}

export function chartSVG(m, kind, w, h, opts = {}) {
  const pts = m.pts;
  if (pts.length < 2) return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Pas assez de points"><text x="${w / 2}" y="${h / 2}" text-anchor="middle">${esc(opts.empty || "Pas assez de points sur cette période")}</text></svg>`;
  const T = 14, B = 22;
  const ys = pts.map(Y_OF[kind]);
  const ref = (kind === "val" || kind === "pos") && show("dep") && !m.onlyDebt ? pts.map((p) => p.dep) : null;
  const av = kind === "val" && m.hasDebt && !S.gross && show("assets") ? pts.map((p) => p.a) : null;
  const bench = kind === "pct" && m.cmp && show("bench") ? pts.map((p) => p.b) : null;
  const pru = kind === "price" && show("pru") ? m.pru : null;
  const goal = kind === "val" && m.target && show("goal") ? m.target : null;
  const all = [...ys, ...(ref || []), ...(av || []), ...(bench || []).filter((v) => v != null), ...(pru ? [pru] : []), ...(goal ? [goal] : [])];
  let mn = Math.min(...all), mx = Math.max(...all);
  if (kind === "gain" || kind === "pct") { mn = Math.min(mn, 0); mx = Math.max(mx, 0); }
  const pad = (mx - mn) * 0.06 || Math.abs(mx) * 0.05 || (kind === "pct" ? 0.01 : 1);
  mn -= pad; mx += pad;
  const { t0, span, R, X, xi } = frame(m, w, opts.big);
  const Y = (v) => T + (h - T - B) * (1 - (v - mn) / (mx - mn));
  const path = (vs) => vs.map((v, k) => (v == null ? "" : `${k && vs[k - 1] != null ? "L" : "M"}${xi(k).toFixed(1)},${Y(v).toFixed(1)}`)).join("");
  const fmtY = kind === "pct" ? (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(Math.abs(mx - mn) < 0.1 ? 1 : 0)} %`
    : kind === "price" && mx < 1000 ? (v) => n2(v).replace(/\.00$/, "") : compact;
  const money = kind !== "pct" ? " money" : "";
  let g = "";
  for (const v of niceTicks(mn, mx, opts.big ? 5 : 4)) {
    const y = Y(v);
    if (y < T - 4 || y > h - B) continue;
    g += `<line class="grid" x1="0" x2="${w - R + 4}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="yl${money}" x="${w}" y="${(y + 3.5).toFixed(1)}" text-anchor="end">${fmtY(v)}</text>`;
  }
  g += `<line class="base" x1="0" x2="${w - R + 4}" y1="${h - B}" y2="${h - B}"/>`;
  for (const t of xTicks(t0, span, X, w - R)) g += `<line class="tick" x1="${t.x.toFixed(1)}" x2="${t.x.toFixed(1)}" y1="${h - B}" y2="${h - B + 4}"/><text class="xl${t.strong ? " strong" : ""}" x="${t.x.toFixed(1)}" y="${h - 6}" text-anchor="middle">${t.l}</text>`;
  if (S.ruler && opts.interactive) {
    const [a, b] = [Math.min(...S.ruler), Math.max(...S.ruler)].map((k) => Math.min(k, pts.length - 1));
    g += `<rect class="band" x="${xi(a).toFixed(1)}" y="${T - 6}" width="${Math.max(1, xi(b) - xi(a)).toFixed(1)}" height="${h - B - T + 6}"/><line class="bandedge" x1="${xi(a).toFixed(1)}" x2="${xi(a).toFixed(1)}" y1="${T - 6}" y2="${h - B}"/><line class="bandedge" x1="${xi(b).toFixed(1)}" x2="${xi(b).toFixed(1)}" y1="${T - 6}" y2="${h - B}"/>`;
  }
  let under = "";
  const zone = (top, bot) => {
    for (let k = 1; k < ys.length; k++) {
      const up = top[k] + top[k - 1] >= bot[k] + bot[k - 1];
      under += `<path class="${up ? "zpos" : "zneg"}" d="M${xi(k - 1).toFixed(1)},${Y(top[k - 1]).toFixed(1)}L${xi(k).toFixed(1)},${Y(top[k]).toFixed(1)}L${xi(k).toFixed(1)},${Y(bot[k]).toFixed(1)}L${xi(k - 1).toFixed(1)},${Y(bot[k - 1]).toFixed(1)}Z"/>`;
    }
  };
  if (ref) {
    if (!av) zone(ys, ref);
    under += `<path class="dep" d="${path(ref)}"/>`;
  } else if (kind === "gain" || kind === "pct") {
    const z = Y(0);
    under += `<line class="zl" x1="0" x2="${w - R}" y1="${z.toFixed(1)}" y2="${z.toFixed(1)}"/>`;
    zone(ys, ys.map(() => 0));
  } else {
    under += `<path class="area" d="${path(ys)}L${xi(ys.length - 1).toFixed(1)},${h - B}L0,${h - B}Z"/>`;
  }
  if (av) under += `<path class="debtband" d="${path(av)}${ys.map((v, k) => `L${xi(ys.length - 1 - k).toFixed(1)},${Y(ys[ys.length - 1 - k]).toFixed(1)}`).join("")}Z"/><path class="assets" d="${path(av)}"/>`;
  if (bench) under += `<path class="bench" d="${path(bench)}"/>`;
  if (pru) under += `<line class="pru" x1="0" x2="${w - R}" y1="${Y(pru).toFixed(1)}" y2="${Y(pru).toFixed(1)}"/>`;
  if (kind === "price" && show("buys")) {
    for (const b of m.buys || []) under += `<circle class="buy${b.kind === "out" ? " sell" : ""}" cx="${xi(b.k).toFixed(1)}" cy="${(h - B - 5).toFixed(1)}" r="3.5"/>`;
  }
  if (show("events") && kind !== "price") {
    const yb = h - B - 7;
    for (const e of m.events || []) {
      const x = xi(e.k).toFixed(1);
      if (e.kind !== "income") under += `<line class="evl" x1="${x}" x2="${x}" y1="${T}" y2="${yb}"/>`;
      under += e.kind === "income" ? `<rect class="ev inc" x="${(x - 2.5).toFixed(1)}" y="${(yb - 2.5).toFixed(1)}" width="5" height="5" transform="rotate(45 ${x} ${yb})"/>`
        : e.kind === "in" ? `<path class="ev in" d="M${x},${yb - 5}l5,8h-10z"/>` : `<path class="ev out" d="M${x},${yb + 4}l5,-8h-10z"/>`;
    }
  }
  if (goal) under += `<line class="goal" x1="0" x2="${w - R}" y1="${Y(goal).toFixed(1)}" y2="${Y(goal).toFixed(1)}"/><text class="ann money" x="4" y="${(Y(goal) - 5).toFixed(1)}">Objectif ${compact(goal)}</text>`;
  let over = "";
  for (const u of m.unc || []) {
    if (u.k1 <= u.k0) continue;
    under += `<rect class="uncband" x="${xi(u.k0).toFixed(1)}" y="${T - 6}" width="${(xi(u.k1) - xi(u.k0)).toFixed(1)}" height="${h - B - T + 6}"/>`;
    const seg = ys.slice(u.k0, u.k1 + 1).map((v, j) => `${j ? "L" : "M"}${xi(u.k0 + j).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    over += `<path class="unc-hide" d="${seg}"/><path class="unc-line" d="${seg}"/>`;
  }
  if ((kind === "val" || kind === "price" || kind === "pos") && show("marks")) {
    const kmax = ys.indexOf(Math.max(...ys)), kmin = ys.indexOf(Math.min(...ys));
    for (const [k, lab, below] of [[kmax, "plus haut", false], [kmin, "plus bas", true]]) {
      if (k === ys.length - 1 || k === 0) continue;
      const x = xi(k), y = Y(ys[k]);
      const low = below && y + 14 > h - B - 2;
      const anchor = low ? (x > w / 2 ? "end" : "start") : x < 60 ? "start" : x > w - R - 60 ? "end" : "middle";
      const tx = low ? (x > w / 2 ? x - 7 : x + 7) : x, ty = low ? y + 3.5 : below ? y + 14 : Math.max(10, y - 7);
      over += `<circle class="mk" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"/><text class="ann money" x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}">${lab} ${kind === "price" ? px(ys[k]) : compact(ys[k])}</text>`;
    }
  }
  const si = S.scrub == null || !opts.interactive ? ys.length - 1 : Math.min(S.scrub, ys.length - 1);
  const cx = xi(si).toFixed(1);
  let cur = "";
  if (S.scrub != null && opts.interactive) {
    cur += `<line class="cursor" x1="${cx}" x2="${cx}" y1="${T - 6}" y2="${h - B}"/>`;
    if (ref) cur += `<circle class="dot2" cx="${cx}" cy="${Y(ref[si]).toFixed(1)}" r="3.5"/>`;
    if (bench && bench[si] != null) cur += `<circle class="dot3" cx="${cx}" cy="${Y(bench[si]).toFixed(1)}" r="3.5"/>`;
  }
  cur += `<circle class="dot" cx="${cx}" cy="${Y(ys[si]).toFixed(1)}" r="4.5"/>`;
  const aria = `Courbe ${m.label}, de ${fmtY(ys[0])} à ${fmtY(ys[ys.length - 1])}. Flèches gauche et droite pour lire une date.`;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" tabindex="0" role="img" aria-label="${esc(aria)}"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" class="hatchl"/></pattern><linearGradient id="ga" x1="0" x2="0" y1="0" y2="1"><stop class="g0" offset="0"/><stop class="g1" offset="1"/></linearGradient></defs>${g}${under}<path class="line" d="${path(ys)}"/>${over}${cur}</svg>`;
}

// --- légende, règle, repère du doigt ----------------------------------------------------------

export function legendHTML(m, kind) {
  const it = [];
  const lg = (k, cls, c, label) => `<button class="lg" type="button" data-a="w-series" data-v="${k}" aria-pressed="${show(k)}"><i class="${cls}" data-css="--c:${c}"></i>${label}</button>`;
  const fixed = (cls, c, label) => `<span class="lg"><i class="${cls}" data-css="--c:${c}"></i>${label}</span>`;
  const evs = (m.events || []).length ? [lg("events", "box", "var(--s6)", "Événements")] : [];
  const marks = lg("marks", "dot", "var(--ink)", "Plus haut, plus bas");
  if (kind === "val") {
    it.push(fixed("", "var(--accent)", m.hasDebt && !S.gross ? "Valeur nette" : m.onlyDebt ? "Solde" : "Valeur"));
    if (!m.onlyDebt) it.push(lg("dep", "dash", "var(--muted)", "Apports"));
    if (m.hasDebt && !S.gross) it.push(lg("assets", "", "var(--s2)", "Avoirs et dettes"));
    if (m.target) it.push(lg("goal", "dash", "var(--s5)", "Objectif"));
    it.push(...evs, marks);
  } else if (kind === "pos") {
    it.push(fixed("", "var(--accent)", "Valeur"), lg("dep", "dash", "var(--muted)", "Investi"), ...evs, marks);
  } else if (kind === "price") {
    it.push(fixed("", "var(--accent)", "Cours"));
    if (m.pru) it.push(lg("pru", "dash", "var(--s4)", "Prix de revient"));
    if ((m.buys || []).length) it.push(lg("buys", "box", "var(--s4)", "Achats et ventes"));
    it.push(marks);
  } else if (kind === "gain") {
    it.push(fixed("", "var(--accent)", "Gain cumulé, versements exclus"), ...evs);
  } else {
    it.push(fixed("", "var(--accent)", "Rendement pondéré"));
    if (m.cmp) it.push(lg("bench", "dash", "var(--s3)", esc(m.cmp.name)));
    it.push(...evs);
  }
  const est = (m.unc || []).length ? fixed("dash", "var(--warn)", "Estimé") : "";
  return `<div class="lgrow">${it[0]}${est}<span class="gran">${granLabel(m.pts)}</span></div>${it.length > 1 ? `<div class="lgrow chips"><span class="lgl">Afficher</span>${it.slice(1).join("")}</div>` : ""}`;
}

export function rulerHTML(m, kind) {
  if (S.rulerOn && !S.ruler) return '<div class="ruler-hint">Glisse sur la courbe d\'une date à l\'autre pour mesurer l\'écart.</div>';
  if (!S.ruler || m.pts.length < 2) return "";
  const [a, b] = [Math.min(...S.ruler), Math.max(...S.ruler)].map((k) => m.pts[Math.min(k, m.pts.length - 1)]);
  const days = Math.round((day(b.d) - day(a.d)) / 864e5);
  let txt;
  if (kind === "price") txt = `Cours ${px(a.price)} → ${px(b.price)} : <b class="${b.price >= a.price ? "pos" : "neg"}">${pct(b.price / a.price - 1)}</b>`;
  else {
    const gain = b.g - a.g, twr = a.r == null || b.r == null ? null : (1 + b.r) / (1 + a.r) - 1;
    txt = `<b class="${b.v >= a.v ? "pos" : "neg"}"><span class="money">${sgnMoney(b.v - a.v)}</span> ${base()}</b> de variation · gain <b class="${gain >= 0 ? "pos" : "neg"}"><span class="money">${sgnMoney(gain)}</span></b>${twr == null ? "" : ` (${pct(twr)})`} · apports <span class="money">${sgnMoney(b.f - a.f)}</span>`;
  }
  return `<div class="ruler-out" role="status"><span class="t">Du <b>${shortDate(a.d)}</b> au <b>${shortDate(b.d)}</b> (${days} j)<br>${txt}</span><button class="x" type="button" data-a="w-ruler-clear" aria-label="Effacer la mesure"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`;
}

// événement le plus proche du point lu (une fenêtre d'environ 1/60 de la largeur)
export function nearEvent(m, k) {
  if (!show("events") || !(m.events || []).length) return null;
  const win = Math.max(1, Math.round(m.pts.length / 60));
  let best = null;
  for (const e of m.events) if (Math.abs(e.k - k) <= win && (!best || Math.abs(e.k - k) < Math.abs(best.k - k))) best = e;
  return best;
}
export const evText = (e) => `${EV[e.kind]} ${sgnMoney(e.v)} ${base()} · ${shortDate(e.d)}`;
const uncAt = (m, k) => (m.unc || []).find((u) => k >= u.k0 && k <= u.k1 && u.k1 > u.k0);

// étiquette au-dessus du doigt : la date, ou l'événement proche
export function flagHTML(m, w) {
  if (S.scrub == null || S.ruler || m.pts.length < 2) return "";
  const k = Math.min(S.scrub, m.pts.length - 1), x = frame(m, w, false).xi(k), e = nearEvent(m, k), u = uncAt(m, k);
  const half = e ? 92 : u ? 70 : 40;
  const left = Math.max(half, Math.min(w - half, x)).toFixed(0);
  const txt = e ? `<span class="money">${evText(e)}</span>` : `${shortDate(m.pts[k].d)}${u ? " · estimé" : ""}`;
  return `<div class="flag${e ? ` ev-${e.kind}` : u ? " ev-unc" : ""}" data-css="left:${left}px">${txt}</div>`;
}

// info-bulle complète du plein écran
export function tipHTML(m, kind, w) {
  if (S.scrub == null || S.ruler || m.pts.length < 2) return "";
  const k = Math.min(S.scrub, m.pts.length - 1), p = m.pts[k], x = frame(m, w, true).xi(k);
  const rows = [];
  const rr = (c, dash, lab, v) => `<div class="r"><i class="${dash ? "dash" : ""}" data-css="--c:${c}"></i><span>${lab}</span><b class="money">${v}</b></div>`;
  if (kind === "val" || kind === "pos") {
    rows.push(rr("var(--accent)", 0, "Valeur", n0(p.v)));
    if (show("dep")) rows.push(rr("var(--muted)", 1, kind === "pos" ? "Investi" : "Départ + apports", n0(p.dep)));
    rows.push(rr("var(--pos)", 0, "Gain", sgnMoney(p.g)));
    if (m.hasDebt && !S.gross && kind === "val" && show("assets")) rows.push(rr("var(--s2)", 0, "Avoirs", n0(p.a)));
  }
  if (kind === "gain") rows.push(rr("var(--accent)", 0, "Gain", sgnMoney(p.g)), rr("var(--muted)", 0, "Rendement", pct(p.r)));
  if (kind === "pct") {
    rows.push(rr("var(--accent)", 0, "Rendement", pct(p.r)));
    if (m.cmp && p.b != null) rows.push(rr("var(--s3)", 1, esc(m.cmp.name), pct(p.b)));
  }
  if (kind === "price") {
    rows.push(rr("var(--accent)", 0, "Cours", px(p.price)));
    if (m.pru && show("pru")) rows.push(rr("var(--s4)", 1, "Prix de revient", px(m.pru)));
  }
  const u = uncAt(m, k), e = nearEvent(m, k);
  if (u) rows.push(`<div class="r evr"><i class="dash" data-css="--c:var(--warn)"></i><span class="wrap">${esc(u.why)}</span><b></b></div>`);
  if (e) rows.push(`<div class="r evr"><i class="box" data-css="--c:${e.kind === "out" ? "var(--neg)" : e.kind === "income" ? "var(--s3)" : "var(--pos)"}"></i><span>${EV[e.kind]} le ${shortDate(e.d)}</span><b class="money">${sgnMoney(e.v)}</b></div>`);
  return `<div class="tip" data-css="left:${(x > w / 2 ? x - 196 : x + 12).toFixed(0)}px"><div class="d">${longDate(p.d)}</div>${rows.join("")}</div>`;
}
