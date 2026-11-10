// Budget : le diagramme de flux (revenus → usage → postes). Deux piles du même total : chaque flux
// relie les tranches qui se recouvrent, aucun n'en croise un autre. Toucher un bloc suit son flux.
import { amount, esc, ibox, ic, n0, pf } from "../../ui.js";
import { base, units } from "../../format.js";
import { UNCAT } from "./bviews.js";
import { catLook } from "./meta.js";

const u = (m) => (m ? units(m) : 0);

export function sankeyData(f) {
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

export function sankeySvg(sd, sel) {
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
  const all = [...sd.srcs, ...sd.mids, ...right], selN = all.find((n) => n.id === sel);
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

export function sankeyInfo(sd, sel) {
  const all = [...sd.srcs, ...sd.mids, ...sd.mids.flatMap((m) => m.kids)], n = all.find((x) => x.id === sel);
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

