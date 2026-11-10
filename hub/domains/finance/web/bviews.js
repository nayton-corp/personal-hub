// Budget : les catégories et la tendance, telles que le serveur les donne (/finance/budget,
// /finance/budget/months). Les barres des catégories sont toutes à la même échelle : la longueur
// dit le montant, la plus grosse fait toute la largeur, et ce qui dépasse la cible continue en
// rouge. Une seule couleur ; le rouge ne sert qu'au dépassement. Une charge fixe n'a pas de
// barre : elle est payée, à telle date, ou attendue vers tel jour.
import { GROUP_LABEL, catMark } from "./meta.js";
import { MOIS, base, monthName, units } from "../../format.js";
import { amount, esc, ic, money, n0, pf, pref } from "../../ui.js";
import { catState, fixedState, rank, yearState } from "./bmodel.js";

export const UNCAT = "a-categoriser";
export const shortMonth = (m) => MOIS[Number(m.slice(5, 7)) - 1];
const u = (m) => (m ? units(m) : 0);
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

// en-tête d'une section repliable, avec sa ligne de résumé une fois repliée
export function foldHead(id, title, open, sum) {
  return `<div class="section-head"><button class="fold-btn" type="button" data-a="bfold" data-v="${id}" aria-expanded="${open}" aria-controls="${id}-body"><h2 class="section-title" id="t-${id}">${title}</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
    ${open ? "" : `<button class="sec-sum" type="button" data-a="bfold" data-v="${id}" aria-label="Déplier ${title}"><span>${sum}</span></button>`}`;
}

// dépenses variables sans cible : comptées dans le reste à vivre, dites à part
const isOff = (l) => (l.group === "variable" || l.group === "mixed") && l.t == null && !l.yearly && l.category !== UNCAT;
export const offTarget = (m) => m.lines.filter(isOff).reduce((t, l) => t + l.s, 0);

// la part d'année d'une catégorie suivie à l'année, ramenée à la période affichée
const yearPart = (c, n) => (c.yearly.target ? (u(c.yearly.target) / 12) * n : 0);
const yearDone = (c) => (c.yearly.target ? u(c.yearly.spent) / u(c.yearly.target) : 0);

function scaled(t, s, scale) {
  const pc = (v) => `${Math.max(0, (v / scale) * 100).toFixed(1)}%`;
  const over = s > t;
  return `<span class="pbar thin sc${over ? " over" : ""}"><span class="trk" data-css="width:${pc(t)}"><i data-css="width:${(Math.min(1, t ? s / t : 0) * 100).toFixed(1)}%"></i></span>${over ? `<i class="ov" data-css="left:${pc(t)};width:${pc(s - t)}"></i>` : ""}</span>`;
}

function yearRow(c, x) {
  const y = c.yearly, done = u(y.spent), goal = y.target ? u(y.target) : null;
  const s = yearState(c), part = yearPart(c, x.n);
  const month = c.s ? ` · ${n0(c.s)} ce mois` : "";
  return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(c.name)}, ${n0(done)}${goal != null ? ` sur ${n0(goal)}` : ""} ${base()} depuis janvier, ${s.txt}">
    ${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)} <span class="pill">par an</span></b><span class="t num">${money(done)}${goal != null ? ` / ${money(goal)}` : ""}</span></span>
    ${goal != null ? scaled(part, part * yearDone(c), x.scale) : ""}
    <span class="crow-st ${s.k}">${s.txt}${month}</span></span></button>`;
}

// une ligne de catégorie : sa barre (variable) ou sa date (fixe), et l'état en mots
function catRow(c, x) {
  if (c.yearly) return yearRow(c, x);
  const fixed = c.group === "fixed";
  const s = fixed ? fixedState(c, x.today) : catState(c);
  const tag = s.k === "bad" && !fixed ? '<span class="pill bad">Dépassé</span>' : "";
  return `<button class="crow" type="button" data-a="cat" data-v="${esc(c.category)}" aria-label="${esc(c.name)}, ${n0(c.s)}${c.t != null ? ` sur ${n0(c.t)}` : ""} ${base()}, ${s.txt}">
    ${catMark(c.category, c.group)}<span><span class="crow-top"><b>${esc(c.name)}${tag}</b><span class="t num">${money(c.s)}${c.t != null ? ` / ${money(c.t)}` : ""}</span></span>
    ${fixed || c.t == null ? "" : scaled(c.t, c.s, x.scale)}
    <span class="crow-st ${s.k}">${s.done ? ic("check") : ""}${s.txt}</span></span></button>`;
}

// B : { bgroup, offOpen } (le filtre venu du diagramme de flux, « Hors cible » déplié) ; flows : /finance/flows
export function categories(m, B, flows) {
  const uncl = m.lines.find((l) => l.category === UNCAT);
  const sum2 = (cs) => [cs.filter((c) => !c.yearly).reduce((t, c) => t + c.s, 0), cs.reduce((t, c) => t + (c.t || 0), 0)];
  const pick = (gs) => m.lines.filter((l) => gs.includes(l.group) && l.category !== UNCAT)
    .sort((x, y) => rank(y) - rank(x) || (y.t ? y.s / y.t : 0) - (x.t ? x.s / x.t : 0) || y.s - x.s);
  if (B.bgroup === "savings" || B.bgroup === "rest") return savingsOrRest(B, flows);
  const vars = B.bgroup === "fixed" ? [] : pick(["variable", "mixed"]);
  const fixed = B.bgroup === "variable" ? [] : pick(["fixed"]);
  const [vs, vt] = sum2(vars), [fs, ft] = sum2(fixed);
  const paid = fixed.filter((c) => c.t != null && (c.state === "paid" || c.state === "over")).length, due = fixed.filter((c) => c.t != null).length;
  const left = fixed.filter((c) => c.t != null && c.state === "ok").reduce((t, c) => t + Math.max(0, c.t - c.s), 0);
  const openFixed = B.bgroup === "fixed" || pref("fixedOpen", false);
  const nOver = m.lines.filter((l) => l.over).length;
  const off = vars.filter(isOff), kept = vars.filter((c) => !isOff(c));
  const x = { n: m.months, today: today(), scale: Math.max(1, ...kept.map((c) => (c.yearly ? yearPart(c, m.months) * Math.max(1, yearDone(c)) : Math.max(c.t || 0, c.s)))) };
  const head = B.bgroup
    ? `<button class="chip" type="button" data-a="bgroupx" aria-label="Retirer le filtre ${GROUP_LABEL[B.bgroup]}">${GROUP_LABEL[B.bgroup]}${ic("close")}</button>`
    : `<span class="hint num">${money(vs + fs)}${vt + ft ? ` / ${money(vt + ft)}` : ""}</span>`;
  const unclRow = uncl && B.bgroup !== "fixed"
    ? `<button class="crow" type="button" data-a="gotodo">${catMark(null)}<span><span class="crow-top"><b>Non classées</b><span class="t num">${amount(uncl.s)}</span></span><span class="crow-st warn">${uncl.count} écriture${uncl.count > 1 ? "s" : ""} à classer dans le journal</span></span></button>` : "";
  const offRow = off.length ? `<button class="crow" type="button" data-a="boff" aria-expanded="${B.offOpen}" aria-label="Hors cible, ${n0(off.reduce((t, c) => t + c.s, 0))} ${base()}, ${off.length} catégorie${off.length > 1 ? "s" : ""}, compté dans le reste à vivre">${catMark("divers", "variable")}<span><span class="crow-top"><b>Hors cible</b><span class="t num">${money(off.reduce((t, c) => t + c.s, 0))}</span></span>
      <span class="crow-st ok">${off.map((c) => esc(c.name)).join(", ")} · compté dans le reste à vivre</span></span></button>${B.offOpen ? `<div class="crow-sub">${off.map((c) => catRow(c, x)).join("")}</div>` : ""}` : "";
  const varPart = vars.length ? `<div class="grp"><span>Variables</span><span class="num">${money(vs)}${vt ? ` / ${money(vt)}` : ""}</span></div>${kept.map((c) => catRow(c, x)).join("")}${offRow}` : "";
  const fixedPart = fixed.length ? `<button class="grp grp-btn" type="button" data-a="bfixed" aria-expanded="${openFixed}" aria-controls="fixed-body"><span>Fixes · <span class="num">${money(fs)}${ft ? ` / ${money(ft)}` : ""}</span></span>
      <span class="grp-st">${due ? `${paid === due ? ic("check") : ""}${paid} sur ${due} payée${due > 1 ? "s" : ""}${left >= 1 ? ` · ${n0(left)} à venir` : ""}` : ""}${ic("down", openFixed ? "up" : "")}</span></button>
      <div id="fixed-body">${openFixed ? fixed.map((c) => catRow(c, x)).join("") : ""}</div>` : "";
  return `<section class="card" id="budCats" aria-labelledby="t-cats">
      <div class="section-head"><h2 class="section-title" id="t-cats">Catégories${nOver ? ` <span class="pill bad">${nOver} dépassée${nOver > 1 ? "s" : ""}</span>` : ""}</h2>${head}</div>
      ${unclRow}${varPart}${fixedPart || ""}${!vars.length && !fixed.length && !uncl ? '<div class="empty">Aucune dépense sur la période.</div>' : ""}
      ${B.bgroup || m.T == null ? "" : `<button class="secondary plan-btn" type="button" data-a="plan" aria-haspopup="dialog">${ic("wallet")}Préparer le budget</button>`}
    </section>`;
}

// le flux filtré sur l'épargne ou le reste : ses postes, sans budget
function savingsOrRest(B, f) {
  const head = `<div class="section-head"><h2 class="section-title" id="t-cats">${B.bgroup === "savings" ? "Épargne" : "Reste"}</h2><button class="chip" type="button" data-a="bgroupx" aria-label="Retirer le filtre">${B.bgroup === "savings" ? "Épargne" : "Reste"}${ic("close")}</button></div>`;
  if (B.bgroup === "rest") return `<section class="card" id="budCats" aria-labelledby="t-cats">${head}<div class="empty">Ni dépensé ni épargné pour l'instant.</div></section>`;
  const items = f ? (f.groups.find((x) => x.group === "savings")?.items || []) : [];
  return `<section class="card" id="budCats" aria-labelledby="t-cats">${head}<div class="grp"><span>Épargne</span><span class="num">${amount(items.reduce((t, i) => t + u(i.total), 0))}</span></div>` +
    items.map((i) => `<div class="crow">${catMark(i.category, "savings")}<span><span class="crow-top"><b>${esc(i.name)}</b><span class="t num">${amount(u(i.total))}</span></span><span class="crow-st ok">${f.income.minor ? `${pf(u(i.total) / u(f.income), 0)} % des revenus` : ""}</span></span></div>`).join("") + "</section>";
}

// tendance : fixes, variables, épargne empilés, comme avant ; en plus, le budget de chaque mois en
// trait et ce qui le dépasse en rouge. Le dépassement vient du serveur, dans le périmètre du
// reste à vivre : le trait se pose donc là où le budget est atteint dans la pile de ce mois.
export function trend(d, P) {
  if (!d) return "";
  const ms = d.series.map((s) => {
    const F = u(s.fixed), V = u(s.variable), goal = s.budget ? u(s.budget) : null;
    const over = goal == null ? 0 : Math.min(V, u(s.over)), line = goal == null ? null : Math.max(0, F + V - (u(s.budgeted_expenses) - goal));
    return { m: s.month, F, V, S: u(s.savings), goal, over, line, yearly: goal != null && F + V - u(s.budgeted_expenses) >= 1 };
  });
  const mx = Math.max(1, ...ms.map((x) => Math.max(x.F + x.V + x.S, x.line || 0)));
  const open = pref("trendOpen", false);
  const spend = ms.map((x) => x.F + x.V);
  const avg = spend.length > 1 ? spend.slice(0, -1).reduce((t, v) => t + v, 0) / (spend.length - 1) : null;
  const last = ms[ms.length - 1];
  const sum = last ? `Dépenses ${shortMonth(last.m)} ${n0(spend[spend.length - 1])}${avg != null ? `, moyenne des mois d'avant ${n0(avg)}` : ""} ${base()}` : "";
  if (!open) return `<section class="card folded" id="trend" aria-labelledby="t-trend">${foldHead("trend", "Tendance sur 6 mois", false, sum)}</section>`;
  const goals = [...new Set(ms.filter((x) => x.goal != null).map((x) => Math.round(x.goal)))];
  return `<section class="card" id="trend" aria-labelledby="t-trend">
      ${foldHead("trend", "Tendance sur 6 mois", true, sum)}
      <p class="hint">Toucher un mois l'affiche.${ms.some((x) => x.yearly) ? " Le trait du budget monte les mois où s'ajoute une dépense suivie à l'année (vacances, entretien) : elle ne compte pas dans le budget du mois." : ""}</p>
      <div class="months" role="group" aria-label="Choisir un mois">${ms.map((x) => {
        const t = x.F + x.V + x.S;
        return `<button class="mcol" type="button" data-a="month" data-v="${x.m}" aria-pressed="${P.period === "m" && P.month === x.m}" aria-label="${monthName(x.m)} : fixes ${n0(x.F)}, variables ${n0(x.V)}, épargne ${n0(x.S)}${x.goal != null ? `, budget ${n0(x.goal)}${x.over >= 1 ? `, dépassé de ${n0(x.over)}` : ""}` : ""}">
          <span class="stack">${x.line != null ? `<span class="goal-line" data-css="bottom:${((x.line / mx) * 100).toFixed(1)}%"></span>` : ""}<span class="bars" data-css="--h:${((t / mx) * 100).toFixed(1)}%"><i data-css="--f:${x.F};--c:var(--s1)"></i><i data-css="--f:${x.V - x.over};--c:var(--s3)"></i>${x.over >= 1 ? `<i data-css="--f:${x.over};--c:var(--neg)"></i>` : ""}<i data-css="--f:${x.S};--c:var(--s2)"></i></span></span><span>${shortMonth(x.m)}</span></button>`;
      }).join("")}</div>
      <div class="legend"><span><i data-css="--c:var(--s1)"></i>Fixes</span><span><i data-css="--c:var(--s3)"></i>Variables</span><span><i data-css="--c:var(--s2)"></i>Épargne</span>${goals.length ? `<span><i data-css="--c:var(--neg)"></i>Au-dessus du budget</span><span><i class="dashk"></i>Budget${goals.length === 1 ? ` ${n0(goals[0])}` : " du mois"}</span>` : ""}</div>
    </section>`;
}
