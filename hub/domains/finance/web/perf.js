// Patrimoine, section Performance : rendement (avec revenus et frais) et risque. Les chiffres
// viennent de /finance/performance (agrégats par compte, par actif, par mois, par année) : aucune
// écriture n'est lue ici. La période et les filtres de l'écran s'appliquent partout. La réserve
// et la marge 3a sont sur l'Accueil, le taux d'épargne dans le Budget, la composition par
// devise dans la Répartition.
import { MOIS, base, date } from "../../format.js";
import { esc, ic, money, n0, pf, sgn, skel } from "../../ui.js";

export const units = (m) => (m ? m.minor / 100 : 0);
export const rate = (s) => (s == null ? null : Number(s));
export const signedMoney = (v) => `<span class="money">${sgn(v)}${n0(v)}</span>`;
export const ratePct = (r) => (r == null ? "—" : `${sgn(r)}${pf(Math.abs(r))} %`);
export const tone = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
// un gain (et son rendement) qui s'arrondit à zéro reste gris : ni gain ni perte
const toneOf = (g, r) => (Math.round(g) === 0 && (r == null || Math.round(r * 1000) === 0) ? "zero" : tone(r ?? g));
// gain en francs puis rendement pondéré, comme la ligne « montant · % » d'avant
export const gainSpan = (g, r) => `<span class="delta ${toneOf(g, r) === "zero" ? "zero" : tone(g)} num">${signedMoney(g)} ${base()}${r == null ? "" : ` · ${ratePct(r)}`}</span>`;

const MOIS1 = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const amt = (v) => `${money(v)} ${base()}`;

// tuile comme sur l'Accueil ; `go` : attributs d'action quand elle mène au détail
function tile(icn, lbl, value, sub, cls = "", go = "") {
  const tag = go ? "button" : "div";
  return `<${tag} class="tile"${go ? ` type="button" ${go}` : ""}><span class="tile-lbl">${ic(icn)}${lbl}</span><span class="tile-amt num ${cls}">${value}</span>${sub ? `<span class="tile-sub">${sub}</span>` : ""}</${tag}>`;
}
const h3 = (t, hint = "") => `<div class="h3">${t}${hint ? `<span>${hint}</span>` : ""}</div>`;
const note = (t) => `<p class="pnote">${t}</p>`;
const pctw = (x) => Math.max(0, Math.min(100, x)).toFixed(1);

// barres de part et d'autre de zéro ; chaque ligne ouvre son élément dans le Détail
function divBars(rows) {
  const m = Math.max(...rows.map((r) => Math.abs(r.v)), 1);
  return `<div class="pbars">${rows.map((r) => {
    const w = (Math.abs(r.v) / m) * 50;
    return `<button class="bar-row go" type="button" data-a="w-jump" data-v="${esc(r.jump)}" aria-label="${esc(r.n)}, ${sgn(r.v)}${n0(r.v)} ${base()}. Voir dans le détail">
      <span class="nm">${esc(r.n)}</span><span class="track div"><b class="${tone(r.v)}" data-css="left:${pctw(r.v >= 0 ? 50 : 50 - w)}%;width:${pctw(w)}%"></b></span><span class="vl ${tone(r.v)}">${signedMoney(r.v)}</span></button>`;
  }).join("")}</div>`;
}

// barres simples (part, frais) : `cls` colore, `vl` est le texte de droite
function plainBars(rows, cls) {
  const m = Math.max(...rows.map((r) => Math.abs(r.v)), 1e-9);
  return `<div class="pbars">${rows.map((r) => `<button class="bar-row go" type="button" data-a="w-jump" data-v="${esc(r.jump)}" aria-label="${esc(r.n)}, ${esc(r.label)}. Voir dans le détail">
      <span class="nm">${esc(r.n)}</span><span class="track plain"><b class="${cls}" data-css="left:0;width:${pctw((Math.abs(r.v) / m) * 100)}%"></b></span><span class="vl">${r.vl}</span></button>`).join("")}</div>`;
}

const accName = (all, id) => {
  const l = all.find((x) => x.acc === id);
  return l ? (l.inst === l.accName ? l.accName : `${l.inst} · ${l.accName}`) : id;
};
const assetName = (all, key) => {
  const l = all.find((x) => x.asset === key);
  return l ? l.name : key;
};

export function perfSummary(perf, label) {
  if (!perf) return "<span>Chargement…</span>";
  const s = perf.summary;
  if (!s) return "<span>Rien à mesurer pour cette sélection</span>";
  const r = rate(s.twr), g = units(s.gain);
  return `<span class="delta ${toneOf(g, r)} num">${r == null ? signedMoney(g) : ratePct(r)}</span><span>${r == null ? "de gain" : `rendement · gain ${signedMoney(g)} ${base()}`} · ${label}</span>`;
}

export function perfSection(ctx) {
  const { src, perf } = ctx;
  if (src && src.status === "error") return `<div class="err-box" role="alert">Performance indisponible : ${esc(src.error.message)}</div>`;
  if (!ctx.sel.length) return '<div class="empty">Aucun élément ne correspond à ces filtres.</div>';
  if (!perf) return skel("block");
  if (!perf.summary || ctx.pts.length < 2) return '<div class="empty">Pas encore assez d\'historique pour mesurer la performance.</div>';
  return (ctx.S.tab === "risk" ? tabRisk : tabRend)(ctx);
}

// --- Rendement --------------------------------------------------------------------------------

function heatCell(r, title) {
  if (r == null) return "<div></div>";
  const a = Math.min(1, Math.abs(r) / 0.06);
  const txt = Math.round(r * 100) === 0 ? "0" : `${r < 0 ? "−" : "+"}${Math.abs(Math.round(r * 100))}`;
  return `<div class="c ${tone(r)}" data-css="--ha:${Math.round(12 + a * 55)}%" title="${title} : ${ratePct(r)}">${txt}</div>`;
}

function tabRend(ctx) {
  const { perf, n, S, all } = ctx;
  const s = perf.summary;
  const twr = rate(s.twr), mwr = rate(s.mwr);
  const fees = units(s.end) > 0 ? -units(s.fees) / units(s.end) : 0;
  const acc = S.view === "acc";
  const groups = acc ? perf.by_account : perf.by_asset;
  const contrib = Object.entries(groups)
    .map(([k, x]) => ({ n: acc ? accName(all, k) : assetName(all, k), v: units(x.gain), jump: `${acc ? "a" : "s"}:${k}` }))
    .filter((r) => Math.abs(r.v) >= 1)
    .sort((a, b) => b.v - a.v)
    .slice(0, 8);
  // rendement de chaque mois de la période, trois dernières années
  const byYear = {};
  for (const m of perf.by_month) {
    byYear[m.period.slice(0, 4)] ??= {};
    byYear[m.period.slice(0, 4)][Number(m.period.slice(5, 7)) - 1] = rate(m.twr);
  }
  const yearTwr = Object.fromEntries(perf.by_year.map((y) => [y.period, rate(y.twr)]));
  const yrs = Object.keys(byYear).sort().slice(-3);
  const heat = perf.by_month.length >= 2 && twr != null
    ? `${h3("Par mois", "en %")}<div class="heat" role="img" aria-label="Rendement par mois, ${yrs.join(", ")}. ${yrs.map((y) => `${y} : ${ratePct(yearTwr[y])}`).join(", ")}">
      <div class="lbl"></div>${MOIS1.map((m) => `<div class="lbl">${m}</div>`).join("")}<div class="lbl">An</div>
      ${yrs.map((y) => `<div class="lbl">${y}</div>${MOIS1.map((_, m) => heatCell(byYear[y][m], `${MOIS[m]} ${y}`)).join("")}${heatCell(yearTwr[y], y).replace('class="c', 'class="c yr')}`).join("")}
    </div>`
    : "";
  const ys = perf.by_year.slice(-5);
  const mx = Math.max(...ys.flatMap((y) => [Math.abs(units(y.net_flows)), Math.abs(units(y.gain))]), 1);
  const years = ys.length
    ? `${h3(`${n ? "Tes apports" : "Ton épargne"} et le marché, par année`)}<div class="pbars">${ys.map((y) => {
      const d = units(y.net_flows), yg = units(y.gain);
      return `<div class="bar-row yr-row"><span class="nm">${y.period}</span>
        <span class="pair"><span class="track plain"><b class="dep" data-css="left:0;width:${pctw((Math.abs(d) / mx) * 100)}%"></b></span><span class="track plain"><b class="${tone(yg)}" data-css="left:0;width:${pctw((Math.abs(yg) / mx) * 100)}%"></b></span></span>
        <span class="vl"><span class="num">${signedMoney(d)}</span><span class="num ${tone(yg)}">${signedMoney(yg)}</span></span></div>`;
    }).join("")}</div>
    <div class="leg2"><span><i class="dep"></i>${n ? "Apports nets" : "Épargne"} (1re ligne)</span><span><i class="pos"></i>Gain du marché (2e ligne)</span></div>`
    : "";
  return `
    <div class="tiles ptiles">
      ${tile("trend", "Rendement", ratePct(twr), "pondéré dans le temps", tone(twr))}
      ${tile("clock", "Par an, pour toi", mwr == null ? "—" : ratePct(mwr), mwr == null ? "dès 1 an de recul" : "selon tes dates de versement", tone(mwr))}
      ${tile("coin", "Revenus", amt(units(s.income)), "dividendes et intérêts", units(s.income) > 0 ? "pos" : "")}
      ${tile("alert", "Frais", amt(-units(s.fees)), fees ? `${pf(fees, 2)} % de la valeur` : "prélevés sur tes relevés", units(s.fees) < 0 ? "neg" : "")}
    </div>
    ${h3("Qui a fait la performance", "toucher pour voir la ligne")}
    ${contrib.length ? divBars(contrib) : note("Rien sur la période.")}
    ${heat}${years}
    ${note("Rendement pondéré : celui des placements, sans l'effet de tes versements (comme VIAC). Par an, pour toi : le taux qui tient compte de tes dates de versement.")}`;
}

// --- Risque -----------------------------------------------------------------------------------

function underwater(ctx) {
  const pts = ctx.pts.filter((p) => p.dd != null);
  if (pts.length < 2) return "";
  const mn = Math.min(...pts.map((p) => p.dd), -0.01);
  const X = (k) => 2 + (336 * k) / (pts.length - 1), Y = (v) => 4 + 58 * (v / mn);
  return `${h3("Recul depuis le dernier sommet")}<svg class="chart uw" viewBox="0 0 340 78" role="img" aria-label="Recul depuis le dernier sommet, au plus ${ratePct(mn)}"><path d="M2,4${pts.map((p, k) => `L${X(k).toFixed(1)},${Y(p.dd).toFixed(1)}`).join("")}L338,4Z"/><text x="2" y="76">${ctx.fmtDate(pts[0].d)}</text><text x="338" y="76" text-anchor="end">${ctx.fmtDate(pts[pts.length - 1].d)}</text></svg>`;
}

function tabRisk(ctx) {
  const { perf, sel, all } = ctx;
  const r = perf.risk;
  if (!r) return note("Pas assez de recul pour mesurer le risque de cette sélection.");
  const dd = rate(r.max_drawdown), vol = rate(r.volatility), yr = rate(perf.summary.twr_yearly);
  const since = (a, b) => Math.max(1, Math.round((Date.parse(b) - Date.parse(a)) / (30.44 * 864e5)));
  const back = dd < 0 ? (r.recovered_on ? tile("clock", "Retour au sommet", `${since(r.trough_on, r.recovered_on)} mois`, `le ${date(r.recovered_on)}`) : tile("clock", "Retour au sommet", "Pas encore", "toujours sous le sommet")) : tile("clock", "Retour au sommet", "—", "aucun recul");
  // ce qui bouge avec les marchés : tout sauf les liquidités et les dettes
  const exposed = sel.filter((l) => l.kind !== "debt" && !l.asset.startsWith("ccy:")).reduce((t, l) => t + Math.max(0, l.value), 0);
  const bad = vol == null ? null : exposed * Math.min(0, (yr ?? 0) - 1.65 * vol);
  const byAsset = {};
  for (const l of sel) if (l.value > 0) byAsset[l.asset] = (byAsset[l.asset] || 0) + l.value;
  const tot = Object.values(byAsset).reduce((t, v) => t + v, 0);
  const big = Object.entries(byAsset).sort((a, b) => b[1] - a[1]).slice(0, 4)
    .map(([k, v]) => ({ n: assetName(all, k), v, jump: `s:${k}`, label: `${pf(v / tot)} % de la sélection`, vl: `${pf(v / tot)} %` }));
  return `
    <div class="tiles ptiles">
      ${tile("trend", "Baisse maximale", dd < 0 ? ratePct(dd) : "Aucune", dd < 0 ? `${date(r.peak_on)} → ${date(r.trough_on)}` : ctx.per.label, dd < 0 ? "neg" : "")}
      ${back}
      ${tile("bolt", "Volatilité", vol == null ? "—" : `${pf(vol)} %`, vol == null ? "dès 8 semaines" : "par an")}
      ${tile("alert", "Mauvaise année", bad == null ? "—" : `${signedMoney(bad)}`, bad == null ? "dès 8 semaines" : "environ 1 année sur 20", bad ? "neg" : "")}
    </div>
    ${underwater(ctx)}
    ${big.length && tot > 0 ? `${h3("Plus grosses lignes", "part de la sélection")}${plainBars(big, "acc")}` : ""}
    ${note("Baisse maximale et volatilité sur le rendement pondéré : tes versements ne les faussent pas. Mauvaise année : ordre de grandeur sur la part placée, pas une prévision.")}`;
}
