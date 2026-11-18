// Budget, la tête de l'écran (refonte du budget, lot B) : le reste à dépenser du plan du mois et
// ce qu'il laisse par jour, la courbe du dépensé cumulé face au mois d'avant, puis une seule carte
// d'action. Les chiffres viennent du serveur (/finance/budget : plan, daily, prev_daily ;
// /finance/budget/upcoming) : ici on met en mots et on dessine, on ne calcule pas le budget.
import { MOIS, base, monthName, units } from "../../format.js";
import { esc, ibox, ic, m0, n0, pref, setPref } from "../../ui.js";
import { store } from "../../store.js";

export const UNCAT = "a-categoriser";
export const LABEL = "Reste à dépenser";
const u = (m) => (m ? units(m) : 0);
const P = store.params;
const iso = () => new Date().toISOString().slice(0, 10);
export const dayMonth = (d) => `${Number(d.slice(8, 10))} ${MOIS[Number(d.slice(5, 7)) - 1]}`;

// des écritures en devise sans change ce jour-là : laissées de côté par le serveur, dites ici
function missingFx(items) {
  if (!items.length) return "";
  const n = items.reduce((t, x) => t + x.count, 0);
  const ccys = [...new Set(items.map((x) => x.currency))].join(", ");
  return `<div class="status warn">${ic("alert")}<span>${n} écriture${n > 1 ? "s" : ""} en ${esc(ccys)} sans taux de change ce jour-là :
    pas comptée${n > 1 ? "s" : ""} ici tant que le cours manque.</span></div>`;
}

// ce qu'on peut dépenser sur la période : le dépensé, le reste du plan et les charges encore
// attendues (revenus attendus − épargne visée − provisions), sinon la somme des cibles
export function ceiling(b, m) {
  const rest = b.plan && b.plan.rest ? u(b.plan.rest) : null;
  const pending = b.plan && b.plan.pending ? u(b.plan.pending) : 0; // charges encore attendues : elles finiront dans la courbe
  return rest != null ? { v: m.spent + rest + pending, label: b.plan.income ? "Disponible" : "Budget" } : m.T != null ? { v: m.T, label: "Budget" } : null;
}

// --- la courbe du mois -------------------------------------------------------------------------

function curve(b, m) {
  const d = b.daily || [], p = b.prev_daily || [];
  if (!d.length) return "";
  const N = Math.max(2, Math.round((Date.parse(b.end) - Date.parse(b.start)) / 864e5));
  const W = 343, H = 104, top = 6, bot = 16;
  const cap = ceiling(b, m), T = cap ? cap.v : null, proj = m.projection;
  const mx = (Math.max(T || 0, proj || 0, ...d.map((x) => x / 100), ...p.map((x) => x / 100)) * 1.08) || 1;
  const X = (i) => (i / (N - 1)) * (W - 2) + 1;
  const Y = (v) => top + (1 - v / mx) * (H - top - bot);
  const path = (arr) => arr.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v / 100).toFixed(1)}`).join("");
  const li = d.length - 1, lv = d[li] / 100, over = T != null && lv > T;
  let s = "";
  if (T != null) s += `<defs><clipPath id="bcOv"><rect x="0" y="0" width="${W}" height="${Y(T).toFixed(1)}"/></clipPath></defs>`;
  if (p.length) s += `<path class="bc-prev" d="${path(p.slice(0, N))}"/>`;
  if (T != null) {
    const y = Y(T).toFixed(1);
    s += `<line class="bc-goal" x1="0" x2="${W}" y1="${y}" y2="${y}"/><text class="bc-glab money" x="${W - 2}" y="${(Y(T) - 4).toFixed(1)}" text-anchor="end">${cap.label} ${n0(T)}</text>`;
  }
  if (m.current && proj != null && li < N - 1) {
    const seg = `M${X(li).toFixed(1)},${Y(lv).toFixed(1)}L${X(N - 1).toFixed(1)},${Y(proj).toFixed(1)}`;
    s += `<path class="bc-proj" d="${seg}"/>${T != null && proj > T ? `<path class="bc-proj over" clip-path="url(#bcOv)" d="${seg}"/>` : ""}`;
  }
  s += `<path class="bc-now" d="${path(d)}"/>${over ? `<path class="bc-now over" clip-path="url(#bcOv)" d="${path(d)}"/>` : ""}`;
  s += `<circle class="bc-dot${over ? " over" : ""}" cx="${X(li).toFixed(1)}" cy="${Y(lv).toFixed(1)}" r="3.5"/>`;
  const f = new Date(`${b.start}T00:00:00Z`), e = new Date(Date.parse(`${b.end}T00:00:00Z`) - 864e5);
  s += `<text class="bc-ax" x="1" y="${H - 2}">${f.getUTCDate()} ${MOIS[f.getUTCMonth()]}</text>`;
  s += `<text class="bc-ax" x="${W - 1}" y="${H - 2}" text-anchor="end">${e.getUTCDate()} ${MOIS[e.getUTCMonth()]}</text>`;
  const prev = p.length ? monthName(prevMonth(b.month)).split(" ")[0] : "";
  const label = `Dépenses cumulées du mois : ${n0(lv)} ${base()} à ce jour${T != null ? `, ${cap.label.toLowerCase()} ${n0(T)}` : ""}${proj != null && m.current ? `, projection ${n0(proj)}` : ""}`;
  return `<svg class="bcurve" viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">${s}</svg>
    <div class="bc-leg"><span><i class="k now"></i>Ce mois</span>${prev ? `<span><i class="k prev"></i>${esc(prev)}</span>` : ""}${m.current && proj != null ?
      `<span><i class="k proj"></i>Projection ${m0(proj)}</span>` : ""}</div>`;
}

export function prevMonth(month) {
  const [y, mo] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, mo - 2, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

// --- la tête -----------------------------------------------------------------------------------

export function hero(b, m) {
  const plan = b.plan || {};
  const rest = plan.rest ? u(plan.rest) : null;
  const q = P.period !== "m";
  const when = !m.current ? "clos" : m.daysLeft < 1 ? "Dernier jour" : `${m.daysLeft} jour${m.daysLeft > 1 ? "s" : ""} restant${m.daysLeft > 1 ? "s" : ""}`;
  if (rest == null) {
    return `<section class="card bflat bhero" aria-labelledby="t-bud">
      <div class="hero-label"><span id="t-bud">${q ? "Dépensé sur 3 mois" : "Dépensé ce mois"}</span><span>${when}</span></div>
      <div class="hero-amount num"><span class="money">${n0(m.spent)}</span><small>${base()}</small></div>
      ${q ? "" : curve(b, m)}${missingFx(m.missingFx)}
      <p class="hint">Sans revenus connus ni cible, il n'y a pas encore de reste à dépenser.</p>
      <button class="primary plan-cta" type="button" data-a="plan" aria-haspopup="dialog">${ic("wallet")}Créer mon budget</button>
    </section>`;
  }
  let line;
  if (!m.current) {
    line = rest >= 0 ? `<span class="bh-ok">${ic("check")}Clos avec ${m0(rest)} ${base()} d'avance</span>`
      : `<span class="bh-bad">${ic("alert")}Clos avec ${m0(-rest)} ${base()} de dépassement</span>`;
  } else if (rest < 0) line = `<span class="bh-bad">${ic("alert")}Dépassé de ${m0(-rest)} ${base()}</span>`;
  else if (q) line = "sur les trois mois";
  else {
    const per = plan.per_day ? u(plan.per_day) : rest;
    const pace = m.T == null ? "" : m.state.short === "Au-dessus du rythme" ? " · au-dessus du rythme" : " · dans le rythme";
    line = `soit <b class="num">${m0(per)} ${base()} par jour</b>${pace}`;
  }
  return `<section class="card bflat bhero" aria-labelledby="t-bud">
    <button class="bh-btn" type="button" data-a="bhead" aria-haspopup="dialog">
      <span class="hero-label"><span id="t-bud">${q ? `${LABEL} sur 3 mois` : LABEL}</span><span class="bh-more">${when} · Détail${ic("chev")}</span></span>
      <span class="hero-amount num${rest < 0 ? " neg" : ""}"><span class="money">${rest < 0 ? "−" : ""}${n0(Math.abs(rest))}</span><small>${base()}</small></span>
      <span class="bh-line">${line}</span>
    </button>
    ${q ? "" : curve(b, m)}${missingFx(m.missingFx)}
  </section>`;
}

// --- une carte d'action, au plus ---------------------------------------------------------------

const hidden = (key) => pref("bactHide", "") === `${iso()}|${key}`;
const card = (key, icon, color, title, text, acts) => hidden(key) ? "" : `<section class="card bflat bact" aria-label="À faire">
  <div class="bact-head">${ibox(ic(icon), color)}<span><b>${title}</b><span>${text}</span></span>
    <button class="bact-x" type="button" data-a="bdismiss" data-v="${esc(key)}" aria-label="Masquer jusqu'à demain">${ic("close")}</button></div>
  <div class="bact-acts">${acts}</div></section>`;

export function action(b, m, up) {
  if (!m.current || P.period !== "m") return "";
  const uncl = m.lines.find((l) => l.category === UNCAT);
  if (uncl && uncl.count) {
    return card("uncat", "help", "var(--warn)", `${uncl.count} écriture${uncl.count > 1 ? "s" : ""} à classer`,
      `${m0(uncl.s)} ${base()} ne sont dans aucune catégorie : le budget reste faux tant qu'elles sont là.`,
      '<button class="primary" type="button" data-a="gotodo">Classer maintenant</button>');
  }
  const over = m.lines.filter((l) => l.group !== "fixed" && l.t != null && !l.yearly && l.state === "over")
    .sort((x, y) => y.s - y.t - (x.s - x.t))[0];
  if (over) {
    return card(`over:${over.category}`, "alert", "var(--neg)", `${esc(over.name)} : ${m0(over.s - over.t)} ${base()} au-dessus`,
      "Reprends-les sur une catégorie qui a de la marge, pour ce mois seulement : le total ne bouge pas.",
      `<button class="primary" type="button" data-a="bmove" data-v="${esc(over.category)}" aria-haspopup="dialog">${ic("swap")}Reprendre</button>
       <button class="secondary" type="button" data-a="cat" data-v="${esc(over.category)}">Changer la cible</button>`);
  }
  const late = up ? up.items.find((x) => x.status === "late") : null;
  if (late) {
    return card(`late:${late.category || late.name}`, "clock", "var(--warn)", `${esc(late.name)} pas encore vu`,
      `Attendu vers le ${dayMonth(late.on)}. Vérifie qu'il n'a pas changé de compte ou de montant.`,
      late.category ? `<button class="secondary" type="button" data-a="cat" data-v="${esc(late.category)}">Voir</button>` : "");
  }
  const gap = b.plan && b.plan.unassigned ? u(b.plan.unassigned) : 0;
  if (gap < -0.5) {
    return card("plan", "wallet", "var(--warn)", `Le plan dépasse les revenus de ${m0(-gap)} ${base()}`,
      "Les cibles et l'épargne visée demandent plus que les revenus attendus du mois.",
      '<button class="secondary" type="button" data-a="plan" aria-haspopup="dialog">Ajuster les cibles</button>');
  }
  return "";
}

export const heroActions = {
  bdismiss: (key) => {
    setPref("bactHide", `${iso()}|${key}`);
    store.notify();
  },
};

