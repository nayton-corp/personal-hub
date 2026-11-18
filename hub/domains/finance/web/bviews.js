// Budget : la tendance sur six mois, telle que le serveur la donne (/finance/budget/months), et
// l'en-tête d'une section repliable. Une seule couleur par groupe ; le rouge ne sert qu'au
// dépassement.
import { MOIS, monthName, units } from "../../format.js";
import { m0, n0 } from "../../ui.js";

export const UNCAT = "a-categoriser";
export const shortMonth = (m) => MOIS[Number(m.slice(5, 7)) - 1];
const u = (m) => (m ? units(m) : 0);

// en-tête d'une section repliable, avec sa ligne de résumé une fois repliée
export function foldHead(id, title, open, sum) {
  return `<div class="section-head"><button class="fold-btn" type="button" data-a="bfold" data-v="${id}" aria-expanded="${open}" aria-controls="${id}-body"><h2 class="section-title" id="t-${id}">${title}</h2><svg class="fold-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
    ${open ? "" : `<button class="sec-sum" type="button" data-a="bfold" data-v="${id}" aria-label="Déplier ${title}"><span>${sum}</span></button>`}`;
}

// tendance : fixes, variables, épargne empilés, comme avant ; en plus, le budget de chaque mois en
// trait et ce qui le dépasse en rouge. Le dépassement vient du serveur, dans le périmètre du
// reste à vivre : le trait se pose donc là où le budget est atteint dans la pile de ce mois.
export function trend(d, P) {
  if (!d) return "";
  const ms = d.series.map((s) => {
    const F = u(s.fixed), V = u(s.variable), goal = s.budget ? u(s.budget) : null;
    const over = goal == null ? 0 : Math.min(V, u(s.over)), line = goal == null ? null : Math.max(0, F + V - (u(s.budgeted_expenses) - goal));
    return { m: s.month, F, V, S: u(s.savings), goal, over, line };
  });
  const mx = Math.max(1, ...ms.map((x) => Math.max(x.F + x.V + x.S, x.line || 0)));
  const goals = [...new Set(ms.filter((x) => x.goal != null).map((x) => Math.round(x.goal)))];
  return `<section class="card" id="trend" aria-labelledby="t-trend">
      <div class="section-head"><h2 class="section-title" id="t-trend">Tendance sur 6 mois</h2></div>
      <p class="hint">Touche un mois pour le détail.</p>
      <div class="months" role="group" aria-label="Choisir un mois">${ms.map((x) => {
        const t = x.F + x.V + x.S;
        return `<button class="mcol" type="button" data-a="month" data-v="${x.m}" aria-pressed="${P.period === "m" && P.month === x.m}" aria-label="${monthName(x.m)} : fixes ${n0(x.F)}, variables ${n0(x.V)}, épargne ${n0(x.S)}${x.goal != null ? `, budget ${n0(x.goal)}${x.over >= 1 ? `, dépassé de ${n0(x.over)}` : ""}` : ""}">
          <span class="stack">${x.line != null ? `<span class="goal-line" data-css="bottom:${((x.line / mx) * 100).toFixed(1)}%"></span>` : ""}<span class="bars" data-css="--h:${((t / mx) * 100).toFixed(1)}%"><i data-css="--f:${x.F};--c:var(--s1)"></i><i data-css="--f:${x.V - x.over};--c:var(--s3)"></i>${x.over >= 1 ? `<i data-css="--f:${x.over};--c:var(--neg)"></i>` : ""}<i data-css="--f:${x.S};--c:var(--s2)"></i></span></span><span>${shortMonth(x.m)}</span></button>`;
      }).join("")}</div>
      <div class="legend"><span><i data-css="--c:var(--s1)"></i>Fixes</span><span><i data-css="--c:var(--s3)"></i>Variables</span><span><i data-css="--c:var(--s2)"></i>Épargne</span>${goals.length ? `<span><i data-css="--c:var(--neg)"></i>Au-dessus du budget</span><span><i class="dashk"></i>Budget${goals.length === 1 ? ` ${m0(goals[0])}` : " du mois"}</span>` : ""}</div>
    </section>`;
}
