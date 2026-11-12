// Patrimoine : la répartition. Par catégorie, disponibilité, objectif, institution, compte ou actif,
// elle se lit dans les lignes de l'écran et filtre au toucher. Par région, secteur ou devise, elle
// vient du serveur (/finance/lookthrough), pour la même sélection que la courbe : liquidités
// comprises, la part qu'un fonds ne détaille pas à part de l'actif sans fiche, une case tirée de
// la classe dite « estimée », et un total égal au patrimoine affiché.
import { LOOK, S, activeCount, fName, foldSection, lines, lookPath, sum } from "./wstate.js";
import { amount, cv, esc, ic, share, skel } from "../../ui.js";
import { assetMark, facetColor, facetMark, lookMark } from "./meta.js";
import { byLabel } from "./wsheets.js";
import { store } from "../../store.js";
import { units } from "./perf.js";

const look = () => LOOK.some(([k]) => k === S.by);
const plural = (n, w) => `${n} ${w}${n > 1 ? "s" : ""}`;
const note = (x) => (x.kind === "undetailed" ? "part que le fonds ne détaille pas" : x.kind === "unknown" ? `${plural(x.count, "actif")} sans fiche`
  : x.estimated ? (S.by === "currency" ? "estimé d'après la devise de cotation" : "estimé d'après la classe") : "");

function allocRows(sel) {
  if (!look()) {
    const g = {};
    for (const l of sel) if (l[S.by] != null) g[l[S.by]] = (g[l[S.by]] || 0) + l.value;
    const rank = Object.keys(g);
    const rows = Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => b[1] - a[1]).map(([k, v], i) => ({ k, v, name: fName(S.by, k), c: S.by === "acc" || S.by === "asset" ? cv(i) : facetColor(S.by, k), rank }));
    return { rows: rows.filter((r) => r.v > 0), owed: rows.filter((r) => r.v < 0).reduce((t, r) => t + r.v, 0) };
  }
  if (!sel.length) return { rows: [], owed: 0, fund: true };
  const e = store.use(lookPath(sel));
  if (e.status === "error") return { error: e.error.message };
  if (!e.data) return { loading: true };
  const d = e.data;
  const rows = d.items.map((x, i) => {
    const tail = x.kind === "undetailed" || x.kind === "unknown";
    return { k: x.bucket, name: x.bucket, v: units(x.value), code: x.code, kind: x.kind, est: x.estimated, tail, note: note(x), c: tail ? "var(--faint)" : cv(i) };
  });
  return { rows: rows.filter((r) => r.v >= 0.5), owed: units(d.owed), fund: true, sure: d.covered == null ? null : Number(d.covered), since: d.compositions_since, unpriced: d.unpriced, shown: sum(sel) };
}

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

// ce que dit la répartition d'elle-même : la part sûre, la date des compositions, l'estimé
function metaLine(a) {
  if (!a.fund || a.sure == null) return "";
  const y = a.since ? a.since.slice(0, 4) : "", when = a.since ? `${a.since.slice(8, 10)}.${a.since.slice(5, 7)}${y === String(new Date().getFullYear()) ? "" : `.${y}`}` : "";
  return `<div class="alloc-meta"><b>${share(a.sure)} détaillés</b>${when ? `<span>compositions du ${when}</span>` : ""}${a.rows.some((r) => r.est) ? '<span class="est-key"><i></i>estimé</span>' : ""}</div>`;
}

// le total réparti, comparé à ce que l'écran affiche : égal, ou l'écart dit en clair
function checkLine(a, total) {
  if (!a.fund) return "";
  const gap = total + a.owed - a.shown;
  const lost = (a.unpriced || []).length ? `<p class="hint">${plural(a.unpriced.length, "position")} sans cours, hors de la répartition : ${esc(a.unpriced.map((u) => u.name).join(", "))}.</p>` : "";
  if (Math.abs(gap) >= 1) return `${lost}<p class="alloc-check off">${ic("info")}<span><b class="money">${amount(total)}</b> répartis : écart de <span class="money">${amount(Math.abs(gap))}</span> avec le patrimoine affiché</span></p>`;
  return `${lost}<p class="alloc-check">${ic("check")}<span><b class="money">${amount(total)}</b> répartis, ${a.owed < 0 ? "le patrimoine affiché avant dettes" : "égal au patrimoine affiché"}</span></p>`;
}

// repliée, la répartition tient en une ligne : ses deux plus gros blocs
function allocSummary(a) {
  if (a.error) return "<span>Répartition indisponible</span>";
  if (a.loading) return "<span>Chargement…</span>";
  const total = a.rows.reduce((t, r) => t + r.v, 0);
  if (!a.rows.length || total <= 0) return "<span>Rien à répartir avec ces filtres</span>";
  const top = a.rows.slice(0, 2).map((r) => `${esc(r.name)} ${Math.round((r.v / total) * 100)} %`).join(" · ");
  return `<span>${top}${a.rows.length > 2 ? ` · ${a.rows.length - 2} de plus` : ""}</span>`;
}

export function allocSection(sel) {
  const a = allocRows(sel);
  const by = `<button class="by-btn head-extra" type="button" data-a="w-byopen" aria-haspopup="dialog">par ${esc(byLabel(S.by).toLowerCase())}${ic("down")}</button>`;
  return foldSection("alloc", "Répartition", by, allocSummary(a), () => allocBody(a));
}

function allocBody(a) {
  if (a.error || a.loading) return a.error ? `<div class="err-box" role="alert">Répartition indisponible : ${esc(a.error)}</div>` : skel("block");
  const rows = a.rows, owed = a.owed;
  const total = rows.reduce((t, r) => t + r.v, 0);
  if (!rows.length || total <= 0) return '<div class="empty">Rien à répartir avec ces filtres.</div>';
  const mark = (r) => (a.fund ? (r.kind === "cash" ? facetMark("cat", "cash") : r.tail ? lookMark("sector", "", r.c) : lookMark(S.by, r.k, r.c, "sm", r.code)) : S.by === "asset" ? assetMark((lines() || []).find((l) => l.asset === r.k) || { name: r.name, cat: "funds" }, "sm") : S.by === "acc" ? facetMark("inst", ((lines() || []).find((l) => l.acc === r.k) || {}).inst || r.name) : facetMark(S.by, r.k));
  const act = (r) => (a.fund ? `data-a="w-bucket" data-v="${esc(r.k)}"` : `data-a="w-alloc" data-v="${esc(r.k)}"`);
  const on = (r) => !a.fund && S.filters[S.by].has(r.k);
  const tm = layout(rows, 0, 0, 340, 170).map(({ r, x, y, w, h }) => {
    const big = w > 70 && h > 38, mid = w > 38 && h > 20;
    return `<g class="tm-cell${on(r) ? " on" : ""}${r.est ? " est" : ""}" ${act(r)}><rect x="${(x + 1.5).toFixed(1)}" y="${(y + 1.5).toFixed(1)}" width="${Math.max(0, w - 3).toFixed(1)}" height="${Math.max(0, h - 3).toFixed(1)}" rx="6" data-css="--c:${r.c}"/>
      ${big ? `<text class="tm-n" x="${(x + 9).toFixed(1)}" y="${(y + 19).toFixed(1)}">${esc(r.name.length > w / 7.5 ? `${r.name.slice(0, Math.max(3, Math.floor(w / 7.5) - 1))}…` : r.name)}</text><text class="tm-v" x="${(x + 9).toFixed(1)}" y="${(y + 35).toFixed(1)}">${Math.round((r.v / total) * 100)} %</text>`
        : mid ? `<text class="tm-v" x="${(x + 6).toFixed(1)}" y="${(y + h / 2 + 4).toFixed(1)}">${Math.round((r.v / total) * 100)} %</text>` : ""}</g>`;
  }).join("");
  const scope = activeCount() ? "De la sélection filtrée" : "De tout le patrimoine";
  const hint = a.fund ? `${scope}, liquidités comprises. Toucher un bloc montre les actifs qui y contribuent.` : `${scope}. Toucher un bloc ou une ligne filtre l'écran.`;
  return `<p class="hint">${hint}</p>${metaLine(a)}
    <svg class="chart tm" viewBox="0 0 340 170" aria-hidden="true">${tm}</svg>
    <div class="alloc-list">${rows.map((r) => `<button class="alloc-row" type="button" ${act(r)} ${a.fund ? 'aria-haspopup="dialog"' : `aria-pressed="${on(r)}"`} aria-label="${esc(r.name)}, ${share(r.v / total)}${r.note ? `, ${esc(r.note)}` : ""}, ${a.fund ? "voir les actifs" : on(r) ? "retirer ce filtre" : "filtrer l'écran sur cette valeur"}">
      ${mark(r)}<span class="alloc-name">${esc(r.name)}${r.note ? `<small>${esc(r.note)}</small>` : ""}</span><span class="alloc-pct num">${share(r.v / total)}</span><span class="alloc-val">${amount(r.v)}</span><span class="fic">${ic(a.fund ? "chev" : on(r) ? "close" : "filter")}</span></button>`).join("")}
    ${owed < 0 ? `<div class="alloc-row static">${facetMark("cat", "debt")}<span class="alloc-name">Dettes, retranchées</span><span class="alloc-pct"></span><span class="alloc-val">${amount(owed)}</span><span></span></div>` : ""}</div>${checkLine(a, total)}`;
}
