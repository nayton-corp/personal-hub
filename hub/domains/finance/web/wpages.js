// Patrimoine : pages d'un compte et d'un actif. La page d'un compte montre ses positions (chacune
// ouvre l'actif dans ce compte), sa performance et d'où vient sa valeur, son montant visé, ses
// apports des douze derniers mois (des totaux), ses réglages. La page d'un actif montre ta
// position (quantité, cours, prix de revient), les comptes qui le détiennent, sa composition
// quand c'est un fonds, et mène aux achats et ventes du Journal.
import { MOIS, MOIS_L, STALE_DAYS, base, date, daysSince } from "../../format.js";
import { S, accLabel, asOf, day, lineId, range, sum } from "./wstate.js";
import { amount, esc, ic, n0, n2, qty, share } from "../../ui.js";
import { assetMark, facetName, instMark } from "./meta.js";
import { compact, pct, px, sgnMoney } from "./wchart.js";
import { rate, units } from "./perf.js";
import { DEBT_KIND, debtDetail } from "./debts.js";
import { monthly } from "./wmodel.js";
import { store } from "../../store.js";

const RATE = 0.04; // rendement supposé pour la date estimée d'un objectif (jamais la hausse passée)
const tone = (v) => (v == null || Math.abs(v) < 1e-9 ? "zero" : v > 0 ? "pos" : "neg");
const section = (title, note, body, extra = "") => `<section class="section"><div class="section-head"><h2 class="section-title">${title}</h2>${extra || (note ? `<span class="sec-note">${note}</span>` : "")}</div>${body}</section>`;
const link = (a, v, icon, text) => `<button class="linkrow" type="button" data-a="${a}" data-v="${esc(v)}">${ic(icon)}<span>${text}</span><span class="go">${ic("chev")}</span></button>`;

// pont : départ, apports, revenus, plus-values et change, frais, arrivée
function bridge(c) {
  const steps = [["Début", units(c.start), true], ["Apports", units(c.net_flows)], ["Revenus", units(c.income)], ["Plus-val.", units(c.price_effect)], ["Frais", units(c.fees)], ["Fin", units(c.end), true]];
  let run = 0, top = 0, low = 0;
  for (const [, v, b] of steps) { run = b ? v : run + v; top = Math.max(top, run); low = Math.min(low, run); }
  const span = top - low || 1, BH = 130, w = 340, bw = (w - 5 * 8) / 6;
  const Y = (v) => 18 + (BH - 38) * (1 - (v - low) / span);
  run = 0;
  return `<svg class="chart bridge" viewBox="0 0 ${w} ${BH}" role="img" aria-label="De ${n0(units(c.start))} à ${n0(units(c.end))} ${base()} : apports ${n0(units(c.net_flows))}, revenus ${n0(units(c.income))}, plus-values ${n0(units(c.price_effect))}, frais ${n0(units(c.fees))}">${steps.map(([name, v, b], k) => {
    const y0 = b ? 0 : run, y1 = b ? v : run + v;
    run = y1;
    const t = Y(Math.max(y0, y1)), h = Math.max(1.5, Math.abs(Y(y0) - Y(y1))), x = k * (bw + 8);
    return `<rect class="${b ? "base" : v >= 0 ? "pos" : "neg"}" x="${x.toFixed(1)}" y="${t.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3"/><text class="money val" x="${(x + bw / 2).toFixed(1)}" y="${(t - 4).toFixed(1)}" text-anchor="middle">${b ? compact(v) : `${v >= 0 ? "+" : "−"}${compact(Math.abs(v))}`}</text><text x="${(x + bw / 2).toFixed(1)}" y="${BH - 4}" text-anchor="middle">${name}</text>`;
  }).join("")}</svg>`;
}

// douze barres : apports nets (ou remboursements) par mois
function bars(data) {
  const w = 340, H = 120, mx = Math.max(...data.map((x) => Math.abs(x.v)), 1), neg = data.some((x) => x.v < 0);
  const z = neg ? 14 + (H - 34) / 2 : H - 20, sc = (neg ? (H - 34) / 2 : H - 34) / mx, bw = w / data.length - 6;
  return `<svg class="chart mbars" viewBox="0 0 ${w} ${H}" role="img" aria-label="Apports nets par mois : ${data.map((x) => `${MOIS_L[Number(x.m.slice(5, 7)) - 1]} ${sgnMoney(x.v)}`).join(", ")}">${data.map((x, k) => {
    const left = k * (bw + 6) + 3, h = Math.max(1.5, Math.abs(x.v) * sc), y = x.v >= 0 ? z - h : z;
    return `<rect class="${x.v >= 0 ? "bp" : "bn"}" x="${left.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3"><title>${MOIS_L[Number(x.m.slice(5, 7)) - 1]} : ${sgnMoney(x.v)} ${base()}</title></rect><text x="${(left + bw / 2).toFixed(1)}" y="${H - 4}" text-anchor="middle">${MOIS[Number(x.m.slice(5, 7)) - 1].slice(0, 1).toUpperCase()}</text>`;
  }).join("")}<line class="base" x1="0" x2="${w}" y1="${z}" y2="${z}"/></svg>`;
}

function perfStrip(c, days) {
  if (!c) return "";
  const g = units(c.gain), r = rate(c.twr), yr = rate(c.twr_yearly);
  return `<div class="strip"><div><span>Gain</span><b class="num ${tone(g)}"><span class="money">${sgnMoney(g)}</span></b></div><div><span>Rendement</span><b class="num ${tone(r)}">${pct(r)}</b></div><div><span>Par an</span><b class="num">${yr == null || days < 365 ? "—" : pct(yr)}</b></div></div>
    ${c.complete ? "" : '<p class="pnote">Des cours manquent sur la période : chiffres partiels.</p>'}`;
}

// objectif : progression, ce qui manque, date estimée sur tes apports moyens et un rendement
// supposé de 4 % par an
function goal(target, value, months) {
  const left = target - value;
  const pace = months && months.length ? months.reduce((t, x) => t + x.v, 0) / 12 : 0;
  let k = null, x = value;
  for (let i = 1; i <= 600 && left > 0; i++) {
    x = x * (1 + RATE / 12) + pace;
    if (x >= target) { k = i; break; }
  }
  const when = k == null ? null : (() => { const d = day(asOf()); d.setUTCMonth(d.getUTCMonth() + k); return d; })();
  const say = left <= 0 ? "Objectif atteint." : !months ? "Calcul de la date…" : when
    ? `Atteint vers <b>${MOIS_L[when.getUTCMonth()]} ${when.getUTCFullYear()}</b> si tu continues à verser <span class="money">${n0(pace)}</span> ${base()} par mois (ta moyenne sur 12 mois) avec un rendement supposé de ${Math.round(RATE * 100)} % par an. La hausse passée des marchés n'est pas prolongée.`
    : "Sans apports réguliers, pas de date estimée.";
  return section("Objectif", "", `<div class="goalbar"><i data-css="width:${Math.max(0, Math.min(100, (value / target) * 100)).toFixed(1)}%"></i></div>
    <div class="goalrow"><span><b class="money">${n0(value)}</b> sur <span class="money">${n0(target)}</span> ${base()} · ${share(Math.max(0, value / target))}</span><span class="sec-note">il manque <span class="money">${n0(Math.max(0, left))}</span></span></div>
    <p class="hint">${say}</p>`, `<button class="by-btn" type="button" data-a="w-series" data-v="goal">${S.hidden.has("goal") ? "Voir sur la courbe" : "Masquer de la courbe"}</button>`);
}

export function accountPage(m, r) {
  const ls = m.sel.slice().sort((a, b) => b.value - a.value), f = ls[0];
  if (!f) return '<div class="empty">Ce compte n\'est plus dans le patrimoine.</div>';
  const days = m.pts.length > 1 ? Math.round((day(m.pts[m.pts.length - 1].d) - day(m.pts[0].d)) / 864e5) : 0;
  const c = m.perf ? m.perf.summary : null;
  if (f.kind === "debt") {
    return section(esc(DEBT_KIND[f.debtKind] || "Dette"), "", debtDetail(f.debt)) + section("Le compte", "", link("w-journal", `a:${f.acc}`, "list", "Voir les paiements dans le Journal"));
  }
  const tot = sum(ls);
  let h = section("Positions", `${ls.length} ligne${ls.length > 1 ? "s" : ""}`, `<div class="list">${ls.map((l) => {
    const c2 = m.perf ? m.perf.by_line[lineId(l)] : null, cash = l.asset.startsWith("ccy:");
    const sub = `<span class="money">${qty(l.qty)}</span> ${esc(l.unit)}${cash ? "" : l.price ? ` × <span class="money">${n2(Number(l.price))}</span> ${esc(l.priceCcy || "")}` : " · sans cours"}`;
    const right = cash ? `<span class="sec-note">${share(l.value / (tot || 1))}</span>` : `<span class="delta ${tone(c2 ? rate(c2.twr) : null)}">${c2 ? pct(rate(c2.twr)) : ""}</span> <span class="sec-note">· ${share(l.value / (tot || 1))}</span>`;
    return `<button class="row go-row" type="button" data-a="w-open" data-v="${esc(`s:${l.asset}`)}">${assetMark(l, "sm")}<span class="row-main"><span class="row-title">${esc(l.name)}</span><span class="row-sub">${sub}</span></span><span class="row-num"><span class="row-val num">${amount(l.value)}</span><span class="row-delta num">${right}</span></span><span class="go">${ic("chev")}</span></button>`;
  }).join("")}</div>`);
  if (c && m.pts.length > 1) h += section("Performance", esc(m.label), `${perfStrip(c, days)}<p class="hint">D'où vient la valeur</p>${bridge(c)}`);
  const months = monthly(ls);
  if (f.target) h += goal(f.target, tot, months);
  if (months && months.length) h += section(f.kind === "cash" ? "Entrées moins sorties par mois" : "Apports par mois", "12 derniers mois, totaux", bars(months.slice(-12)));
  const fresh = (store.data("/finance/freshness") || { items: [] }).items.find((x) => x.account_id === f.acc);
  const age = fresh ? daysSince(fresh.last_data) : null, stale = age == null || age > STALE_DAYS;
  h += section("Le compte", "", `<dl class="dl info">
      <dt>Institution</dt><dd>${esc(f.inst)}</dd><dt>Nature</dt><dd>${esc(facetName("cat", f.cat))}</dd>
      <dt>Disponibilité</dt><dd>${esc(facetName("liq", f.liq))}</dd><dt>Objectif</dt><dd>${esc(facetName("goal", f.goal))}</dd>
      <dt>Dernier relevé</dt><dd${stale ? ' class="warn"' : ""}>${fresh && fresh.last_data ? date(fresh.last_data) : "aucun"}${stale ? ' · <button class="linkish" type="button" data-a="rubric" data-v="conn">Sources</button>' : ""}</dd></dl>
    ${link("w-journal", `a:${f.acc}`, "list", "Voir les écritures dans le Journal")}
    ${link("acc-edit", f.acc, "edit", f.target ? "Modifier le compte et son objectif" : "Modifier le compte, fixer un objectif")}`);
  return h;
}

// composition d'un fonds : sa part dans chaque région, d'après la transparence des fonds
function composition(isin) {
  const e = store.use("/finance/lookthrough?dimension=region");
  if (!e.data) return "";
  const rows = [];
  let tot = 0;
  for (const b of e.data.items) {
    const a = (b.assets || []).find((x) => x.isin === isin);
    if (a) { rows.push([b.bucket, units(a.value)]); tot += units(a.value); }
  }
  if (rows.length < 2 || tot <= 0) return "";
  rows.sort((a, b) => b[1] - a[1]);
  return section("Régions dans le fonds", "transparence des fonds", rows.map(([n, v], k) => `<div class="alloc-row static"><i class="dotk" data-css="--c:var(--s${(k % 7) + 1})"></i><span class="alloc-name">${esc(n)}</span><span class="alloc-pct num">${share(v / tot)}</span><span class="alloc-val"><span class="minibar" data-css="--c:var(--s${(k % 7) + 1})"><i data-css="width:${((v / tot) * 100).toFixed(1)}%"></i></span></span></div>`).join(""));
}

export function assetPage(m, all, r) {
  const ls = m.sel, f = ls[0] || all.find((l) => l.asset === r.id);
  if (!f) return '<div class="empty">Cet actif n\'est plus dans le patrimoine.</div>';
  const cash = f.asset.startsWith("ccy:");
  const days = m.pts.length > 1 && m.pts[0].v != null ? Math.round((day(m.pts[m.pts.length - 1].d) - day(m.pts[0].d)) / 864e5) : 0;
  const c = m.perf ? m.perf.summary : null;
  let h = "";
  if (!cash) {
    const q = m.qty, cost = m.cost, value = sum(ls), lat = cost != null ? value - cost : null;
    h += section("Ma position", r.from && S.where === "here" ? `dans ${esc(f.inst)}` : "tous comptes", `<div class="strip">
      <div><span>Quantité</span><b class="num money">${qty(q)}</b></div><div><span>Cours</span><b class="num">${f.price ? `${px(Number(f.price))} <small>${esc(f.priceCcy || "")}</small>` : "—"}</b></div>
      <div><span>Prix de revient</span><b class="num">${cost != null && q ? `<span class="money">${px(cost / q)}</span>` : "—"}</b></div>
      <div><span>Gain latent</span><b class="num ${tone(lat)}">${lat == null ? "—" : `<span class="money">${sgnMoney(lat)}</span>`}</b></div>
      <div><span>Rendement ${S.custom ? "" : S.period}</span><b class="num ${tone(c ? rate(c.twr) : null)}">${c ? pct(rate(c.twr)) : "—"}</b></div>
      <div><span>Par an</span><b class="num">${c && days >= 365 && rate(c.twr_yearly) != null ? pct(rate(c.twr_yearly)) : "—"}</b></div></div>
      ${cost == null ? '<p class="pnote">Prix de revient inconnu pour une partie des parts.</p>' : ""}`);
  }
  const held = all.filter((l) => l.asset === r.id), tot = sum(held);
  h += section("Détenu dans", `${new Set(held.map((l) => l.acc)).size} compte(s) · ${amount(tot)}`, `<div class="list">${held.slice().sort((a, b) => b.value - a.value).map((l) => `<button class="row go-row" type="button" data-a="w-open" data-v="${esc(`a:${l.acc}`)}">${instMark(l.inst, "sm")}
      <span class="row-main"><span class="row-title">${esc(accLabel(l))}${l.acc === r.from ? ' <span class="sec-note">· ici</span>' : ""}</span><span class="row-sub"><span class="money">${qty(l.qty)}</span> ${esc(l.unit)} · ${esc(facetName("liq", l.liq))}</span>
        <span class="minibar"><i data-css="width:${Math.max(0, Math.min(100, (l.value / (tot || 1)) * 100)).toFixed(1)}%"></i></span></span>
      <span class="row-num"><span class="row-val num">${amount(l.value)}</span><span class="row-delta sec-note">${share(l.value / (tot || 1))} de l'actif</span></span><span class="go">${ic("chev")}</span></button>`).join("")}</div>`);
  if (f.isin) h += composition(f.isin);
  h += section(cash ? "La devise" : "L'actif", "", `<dl class="dl info">
      <dt>Type</dt><dd>${esc(facetName("cat", f.cat))}</dd>${f.isin && !f.symbol ? `<dt>ISIN</dt><dd class="mono">${esc(f.isin)}</dd>` : ""}
      ${f.priceCcy ? `<dt>Devise de cotation</dt><dd>${esc(f.priceCcy)}</dd>` : ""}${f.priceDate ? `<dt>Dernier cours</dt><dd>${date(f.priceDate)}</dd>` : ""}</dl>
    ${f.isin ? link("w-journal", `s:${f.asset}`, "list", "Voir les achats et ventes") : ""}`);
  return h + `<p class="hint pad">${esc(range().label)} · période partagée avec le patrimoine.</p>`;
}
