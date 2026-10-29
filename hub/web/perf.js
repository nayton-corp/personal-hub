// Patrimoine, section Performance : rendement, revenus et frais, risque, trajectoire. Les chiffres
// viennent de /finance/performance (agrégats par compte, par actif, par mois, par année), de
// /finance/kpis, /finance/budget/months et /finance/lookthrough : aucune écriture n'est lue ici.
// La période et les filtres de l'écran s'appliquent partout, sauf deux exceptions écrites à
// l'écran : Revenus et frais portent sur 12 mois, Trajectoire sur tout le patrimoine.
import { MOIS, base, date } from "./format.js";
import { cv, esc, ic, money, n0, pf, sgn } from "./ui.js";

export const units = (m) => (m ? m.minor / 100 : 0);
export const rate = (s) => (s == null ? null : Number(s));
export const signedMoney = (v) => `<span class="money">${sgn(v)}${n0(v)}</span>`;
export const ratePct = (r) => (r == null ? "—" : `${sgn(r)}${pf(Math.abs(r))} %`);
export const tone = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
// gain en francs puis rendement pondéré, comme la ligne « montant · % » d'avant
export const gainSpan = (g, r) => `<span class="delta ${tone(g)} num">${signedMoney(g)} ${base()}${r == null ? "" : ` · ${ratePct(r)}`}</span>`;

const MOIS1 = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const TAX_RATES = [0.15, 0.2, 0.25, 0.3, 0.35, 0.4];
const SAFE_WITHDRAWAL = 0.035;
const RESERVE_MONTHS = 6;
const YEARS_AHEAD = 20;
const FAN = [0.01, 0.04, 0.065]; // bas, milieu, haut de la projection, par an
const amt = (v) => `${money(v)} ${base()}`;
const months1 = (x) => `${x.toFixed(1).replace(".", ",")} mois`;

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
  return `<span class="delta ${tone(r ?? g)} num">${r == null ? signedMoney(g) : ratePct(r)}</span><span>${r == null ? "de gain" : `rendement · gain ${signedMoney(g)} ${base()}`} · ${label}</span>`;
}

export function perfSection(ctx) {
  const { src, perf } = ctx;
  if (src && src.status === "error") return `<div class="err-box" role="alert">Performance indisponible : ${esc(src.error.message)}</div>`;
  if (!ctx.sel.length) return '<div class="empty">Aucun élément ne correspond à ces filtres.</div>';
  if (!perf) return '<div class="loading">Chargement…</div>';
  if (!perf.summary || ctx.pts.length < 2) return '<div class="empty">Pas encore assez d\'historique pour mesurer la performance.</div>';
  return { rend: tabRend, rev: tabRev, risk: tabRisk, traj: tabTraj }[ctx.S.tab](ctx);
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
  const twr = rate(s.twr), mwr = rate(s.mwr), g = units(s.gain), flows = units(s.net_flows);
  const acc = S.view === "acc";
  const groups = acc ? perf.by_account : perf.by_asset;
  const contrib = Object.entries(groups)
    .map(([k, x]) => ({ n: acc ? accName(all, k) : assetName(all, k), v: units(x.gain), jump: `${acc ? "a" : "s"}:${k}` }))
    .filter((r) => Math.abs(r.v) >= 1)
    .sort((a, b) => b.v - a.v)
    .slice(0, 8);
  // rendement de chaque mois de la période, trois dernières années
  const byYear = {};
  for (const m of perf.by_month) (byYear[m.period.slice(0, 4)] = byYear[m.period.slice(0, 4)] || {})[Number(m.period.slice(5, 7)) - 1] = rate(m.twr);
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
      ${tile("coin", "Gain", signedMoney(g), `dont revenus ${amt(units(s.income))}`, tone(g))}
      ${tile("piggy", n ? "Apports nets" : "Épargne", signedMoney(flows), "versements moins retraits")}
    </div>
    ${h3("Qui a fait la performance", "toucher pour voir la ligne")}
    ${contrib.length ? divBars(contrib) : note("Rien sur la période.")}
    ${heat}${years}
    ${note("Rendement pondéré : celui des placements, sans l'effet de tes versements (comme VIAC). Par an, pour toi : le taux qui tient compte de tes dates de versement.")}`;
}

// --- Revenus et frais (12 mois) ---------------------------------------------------------------

function tabRev(ctx) {
  const { year, kpis, all, S } = ctx;
  const head = note("Ces chiffres portent toujours sur les 12 derniers mois, quelle que soit la période choisie.");
  if (!year || year.status === "error") return `${head}<div class="err-box" role="alert">Indisponible${year ? ` : ${esc(year.error.message)}` : ""}</div>`;
  if (!year.data) return `${head}<div class="loading">Chargement…</div>`;
  const y = year.data.summary;
  if (!y) return `${head}${note("Rien sur les 12 derniers mois.")}`;
  const inc = units(y.income), fees = -units(y.fees), value = units(y.end);
  const byAcc = Object.entries(year.data.by_account);
  const feeRows = byAcc.map(([id, x]) => ({ id, v: -units(x.fees), end: units(x.end) })).filter((r) => r.v >= 1).sort((a, b) => b.v - a.v)
    .map((r) => ({ n: accName(all, r.id), v: r.v, jump: `a:${r.id}`, label: `${n0(r.v)} ${base()} de frais`, vl: `${money(r.v)}${r.end > 0 ? ` · ${pf(r.v / r.end, 2)} %` : ""}` }));
  const incRows = byAcc.map(([id, x]) => ({ id, v: units(x.income) })).filter((r) => r.v >= 1).sort((a, b) => b.v - a.v)
    .map((r) => ({ n: accName(all, r.id), v: r.v, jump: `a:${r.id}`, label: `${n0(r.v)} ${base()} de revenus`, vl: money(r.v) }));
  const p3 = kpis && kpis.data ? kpis.data.pillar3a : null;
  let pillar = "";
  if (p3) {
    const paid = units(p3.paid), saved = paid * S.tax;
    pillar = `${h3(`Pilier 3a ${p3.year}, avec l'impôt`)}
      <div class="tiles ptiles">
        ${tile("shield", "Impôt économisé", amt(saved), `<span class="money">${n0(paid)}</span> versés × ${pf(S.tax, 0)} %`, "pos")}
        ${tile("piggy", "Marge 3a restante", amt(units(p3.margin)), `plafond <span class="money">${n0(units(p3.cap))}</span>`)}
      </div>
      <div class="setline"><span>Ton taux marginal d'impôt</span><div class="scroll-x"><div class="seg small" role="group" aria-label="Taux marginal d'impôt">${TAX_RATES.map((t) => `<button type="button" data-a="w-tax" data-v="${t}" aria-pressed="${Math.abs(S.tax - t) < 1e-9}">${pf(t, 0)} %</button>`).join("")}</div></div></div>
      ${note("Estimation gardée sur cet appareil : l'impôt économisé dépend de ton revenu et de ta commune.")}`;
  }
  return `${head}
    <div class="tiles ptiles">
      ${tile("coin", "Revenus", amt(inc), `<span class="money">${n0(inc / 12)}</span> par mois${value > 0 ? ` · ${pf(inc / value)} %` : ""}`, inc > 0 ? "pos" : "")}
      ${tile("alert", "Frais", amt(fees), value > 0 ? `${pf(fees / value, 2)} % de la valeur` : "", fees > 0 ? "neg" : "")}
    </div>
    ${incRows.length ? `${h3("Revenus par compte", "intérêts, dividendes, rendements")}${plainBars(incRows, "pos")}` : ""}
    ${h3("Frais par compte", "toucher pour voir le compte")}
    ${feeRows.length ? plainBars(feeRows, "neg") : note("Aucun frais relevé sur cette sélection.")}
    ${note("Frais prélevés sur tes relevés (catégorie « frais de placement »). Les frais internes des fonds ne sont pas comptés : ils sont déjà dans les cours.")}
    ${pillar}`;
}

// --- Risque -----------------------------------------------------------------------------------

function underwater(ctx) {
  const pts = ctx.pts.filter((p) => p.dd != null);
  if (pts.length < 2) return "";
  const mn = Math.min(...pts.map((p) => p.dd), -0.01);
  const X = (k) => 2 + (336 * k) / (pts.length - 1), Y = (v) => 4 + 58 * (v / mn);
  return `${h3("Recul depuis le dernier sommet")}<svg class="chart uw" viewBox="0 0 340 78" role="img" aria-label="Recul depuis le dernier sommet, au plus ${ratePct(mn)}"><path d="M2,4${pts.map((p, k) => `L${X(k).toFixed(1)},${Y(p.dd).toFixed(1)}`).join("")}L338,4Z"/><text x="2" y="76">${ctx.fmtDate(pts[0].d)}</text><text x="338" y="76" text-anchor="end">${ctx.fmtDate(pts[pts.length - 1].d)}</text></svg>`;
}

// exposition aux devises : liquidités par devise, crypto à part, fonds selon leur composition
function currencies(ctx) {
  const ex = {};
  const look = ctx.look && ctx.look.data ? ctx.look.data.items.filter((x) => x.weight != null) : [];
  const add = (k, v) => { ex[k] = (ex[k] || 0) + v; };
  for (const l of ctx.sel) {
    if (l.kind === "debt" || l.value <= 0) continue;
    if (l.asset.startsWith("ccy:")) add(l.unit, l.value);
    else if (l.cat === "crypto") add("Crypto", l.value);
    else if (look.length) for (const x of look) add(x.bucket, l.value * Number(x.weight));
    else add(l.priceCcy || "Autres", l.value);
  }
  const tot = Object.values(ex).reduce((t, v) => t + v, 0);
  if (tot <= 0) return "";
  let rows = Object.entries(ex).sort((a, b) => b[1] - a[1]);
  if (rows.length > 5) rows = [...rows.slice(0, 4), ["Autres", rows.slice(4).reduce((t, [, v]) => t + v, 0)]];
  return `${h3("Exposition aux devises", look.length ? "fonds selon leur composition" : "devise de cotation")}
    <div class="stackbar" aria-hidden="true">${rows.map(([, v], i) => `<i data-css="--f:${(v / tot).toFixed(4)};--c:${cv(i)}"></i>`).join("")}</div>
    <div class="leg2">${rows.map(([k, v], i) => `<span><i data-css="--c:${cv(i)}"></i>${esc(k)} ${pf(v / tot, 0)} %</span>`).join("")}</div>`;
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
    ${currencies(ctx)}
    ${note("Baisse maximale et volatilité sur le rendement pondéré : tes versements ne les faussent pas. Mauvaise année : ordre de grandeur sur la part placée, pas une prévision.")}`;
}

// --- Trajectoire (tout le patrimoine) ---------------------------------------------------------

function fan(start, yearly, from) {
  const proj = (r) => Array.from({ length: YEARS_AHEAD + 1 }, (_, y) => {
    let v = start;
    for (let k = 0; k < y; k++) v = v * (1 + r) + yearly;
    return v;
  });
  const [lo, mid, hi] = FAN.map(proj);
  const mx = Math.max(...hi, 1), mn = Math.min(0, ...lo);
  const X = (y) => 4 + (332 * y) / YEARS_AHEAD, Y = (v) => 8 + 112 * (1 - (v - mn) / (mx - mn));
  const line = (vs) => vs.map((v, y) => `${y ? "L" : "M"}${X(y).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const band = `${line(hi)}${lo.slice().reverse().map((v, k) => `L${X(YEARS_AHEAD - k).toFixed(1)},${Y(v).toFixed(1)}`).join("")}Z`;
  const end = mid[YEARS_AHEAD];
  return `<svg class="chart fan" viewBox="0 0 340 140" role="img" aria-label="Projection sur ${YEARS_AHEAD} ans : environ ${n0(end / 1000)} mille ${base()} au milieu de la bande">
    <path class="band" d="${band}"/><path class="line" d="${line(mid)}"/>
    <text x="4" y="136">${from}</text><text x="170" y="136" text-anchor="middle">${from + YEARS_AHEAD / 2}</text><text x="336" y="136" text-anchor="end">${from + YEARS_AHEAD}</text>
    <text class="money val" x="336" y="${(Y(end) - 6).toFixed(1)}" text-anchor="end">${n0(end / 1000)}k</text></svg>`;
}

function tabTraj(ctx) {
  const { n, all, kpis, months, asOf } = ctx;
  const head = n ? '<div class="callout">Cet onglet porte sur tout le patrimoine : les filtres ne s\'y appliquent pas.</div>' : "";
  if ([kpis, months].some((e) => e && e.status === "error")) return `${head}<div class="err-box" role="alert">Indisponible : ${esc((kpis.error || months.error).message)}</div>`;
  if (!kpis.data || !months.data) return `${head}<div class="loading">Chargement…</div>`;
  const k = kpis.data, ms = months.data.series;
  const income = ms.reduce((t, m) => t + units(m.income), 0), saved = ms.reduce((t, m) => t + units(m.savings), 0);
  const spentMonths = ms.filter((m) => Math.abs(units(m.expenses)) > 0);
  const spend = spentMonths.length ? spentMonths.reduce((t, m) => t + Math.abs(units(m.expenses)), 0) / spentMonths.length : 0;
  const liquid = units(k.liquid), cover = rate(k.months_covered);
  const invested = all.filter((l) => l.cat === "funds" || l.cat === "crypto").reduce((t, l) => t + Math.max(0, l.value), 0);
  const net = all.reduce((t, l) => t + l.value, 0);
  const fi = spend > 0 ? (invested * SAFE_WITHDRAWAL) / (spend * 12) : null;
  const dormant = spend > 0 ? liquid - RESERVE_MONTHS * spend : 0;
  return `${head}
    <div class="tiles ptiles">
      ${tile("piggy", "Taux d'épargne", income > 0 ? `${pf(saved / income, 0)} %` : "—", `${signedMoney(saved)} sur 12 mois`)}
      ${tile("shield", "Réserve", cover == null ? "—" : months1(cover), "de dépenses en liquidités", cover != null && cover < 3 ? "neg" : "", 'data-a="w-only" data-v="cat|cash" aria-label="Réserve : voir les liquidités"')}
    </div>
    ${cover != null && cover > RESERVE_MONTHS && dormant > 0 ? `<div class="callout">Ta réserve dépasse ${RESERVE_MONTHS} mois de dépenses : environ <b>${amt(dormant)}</b> restent sur des comptes à presque 0 %. À 4 % par an, cela ferait de l'ordre de ${amt(dormant * 0.04)} par an.</div>` : ""}
    ${fi == null ? "" : `${h3("Indépendance financière", `retrait de ${pf(SAFE_WITHDRAWAL)} % par an`)}
    <div class="gauge" role="img" aria-label="${pf(Math.min(fi, 9.99), 0)} % de tes dépenses couvertes"><b data-css="width:${pctw(fi * 100)}%"></b></div>
    ${note(`Tes placements (<span class="money">${n0(invested)}</span> ${base()}) couvriraient <b>${pf(fi, 0)} %</b> de tes dépenses moyennes (<span class="money">${n0(spend)}</span> ${base()} par mois).`)}`}
    ${h3(`Dans ${YEARS_AHEAD} ans`, saved > 0 ? "à ton rythme d'épargne actuel" : "sans nouvelle épargne")}
    ${fan(net, Math.max(0, saved), Number(asOf.slice(0, 4)))}
    ${note(`Bande entre ${pf(FAN[0], 0)} % et ${pf(FAN[2])} % par an, ligne à ${pf(FAN[1], 0)} %. Une illustration, pas une prévision.`)}`;
}
