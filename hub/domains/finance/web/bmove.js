// Budget, les panneaux du plan (refonte du budget, lots A, B et D) : le mois en détail (revenus
// attendus, épargne visée, cibles, non attribué), les revenus attendus à saisir, et « Reprendre »
// un dépassement sur une catégorie qui a de la marge, pour ce mois seulement (move_budget). Tout
// passe par une proposition validée avec Face ID.
import { base, monthName, parseAmount, toMinor, units } from "../../format.js";
import { SH, SHEETS, amount, closeSheet, esc, failure, ibox, ic, m0, openSheet, pf, renderSheet, skel, toast } from "../../ui.js";
import { catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { prevMonth } from "./bhero.js";
import { store } from "../../store.js";

const P = store.params;
const u = (m) => (m ? units(m) : 0);
const cur = () => store.data(`/finance/budget?month=${P.month}&period=${P.period}`);
const flows = () => store.data(`/finance/flows?month=${P.month}&period=${P.period}`);
const kv = (icon, color, k, v, s = "") => `<div class="kv">${ibox(ic(icon), color, "sm")}<span>${k}${s ? `<span class="s">${s}</span>` : ""}</span><b class="num">${v}</b></div>`;
const signedAmount = (v) => `${v < 0 ? "−" : ""}${amount(Math.abs(v))}`;

// --- le mois en détail ------------------------------------------------------------------------

SHEETS.bhead = () => {
  const b = cur();
  if (!b) return { title: "Le mois en détail", body: skel("block") };
  const p = b.plan, f = flows();
  const spent = u(b.budgeted_expenses), proj = b.projection ? u(b.projection) : null;
  const d = b.daily || [], pd = b.prev_daily || [], i = d.length - 1;
  const cmp = i >= 0 && pd.length > i ? (d[i] - pd[i]) / 100 : null;
  const src = p.income_source === "set" ? "saisis par toi" : p.income_source === "average" ? "moyenne des trois mois d'avant" : "aucun revenu connu";
  const unassigned = p.unassigned ? u(p.unassigned) : null;
  const saved = f ? u(f.groups.find((x) => x.group === "savings")?.total) : null;
  const lines = p.savings_lines.map((s) => kv("piggy", "var(--s2)", esc(s.name), `${m0(u(s.done))} / ${m0(u(s.target))}`, u(s.done) >= u(s.target) ? "versé" : "à verser")).join("");
  return {
    title: `${esc(monthName(b.month).replace(/^./, (c) => c.toUpperCase()))} en détail`,
    body: `<h3>Le plan</h3>
      ${kv("arrowin", "var(--s2)", "Revenus attendus", p.income ? amount(u(p.income)) : "—", src)}
      ${kv("piggy", "var(--s2)", "Épargne visée", amount(u(p.savings)))}
      ${kv("wallet", "var(--s1)", "Cibles des dépenses", amount(u(p.targets)), "fixes et variables, provisions de l'année comprises")}
      ${unassigned != null ? kv("sliders", unassigned < 0 ? "var(--neg)" : "var(--s4)", "Non attribué", signedAmount(unassigned), unassigned < 0 ? "le plan dépasse les revenus" : "ni ciblé ni épargné") : ""}
      <h3>Le mois</h3>
      ${kv("cart", "var(--s3)", "Dépensé", amount(spent), "hors provisions de l'année et hors budget")}
      ${p.rest ? kv("check", "var(--accent)", "Reste à dépenser", signedAmount(u(p.rest)), p.income ? "revenus attendus − épargne visée − dépensé" : "cibles − dépensé") : ""}
      ${proj != null && b.current ? kv("trend", "var(--s4)", "Projection fin du mois", amount(proj)) : ""}
      ${cmp != null ? kv("calendar", "var(--s6)", `Au même jour en ${esc(monthName(prevMonth(b.month)).split(" ")[0])}`, `${cmp > 0 ? "+" : "−"}${m0(Math.abs(cmp))} ${base()}`, cmp > 0 ? "tu dépenses plus vite" : "tu dépenses moins vite") : ""}
      ${saved != null && f && u(f.income) ? kv("piggy", "var(--s2)", "Épargné", amount(saved), `${pf(saved / u(f.income), 0)} % des revenus reçus`) : ""}
      ${lines ? `<h3>Épargne visée</h3>${lines}` : ""}
      <p class="hint">Le reste = revenus attendus − épargne visée − dépensé. Les catégories hors budget et les provisions de l'année n'y comptent pas.</p>`,
    foot: `<button class="secondary" type="button" data-a="bincome" aria-haspopup="dialog">${ic("arrowin")}Revenus attendus</button>
      <button class="secondary" type="button" data-a="plan" aria-haspopup="dialog">${ic("sliders")}Ajuster les cibles</button>`,
  };
};

// --- revenus attendus ---------------------------------------------------------------------------

SHEETS.bincome = (_a, sh) => {
  const b = store.data(`/finance/budget?month=${store.today}&period=m`);
  if (!b) return { title: "Revenus attendus", body: skel("block") };
  const p = b.plan, set = p.income_source === "set";
  if (sh.tmp == null) sh.tmp = set && p.income ? Math.round(u(p.income)) : "";
  return {
    title: `${ic("arrowin")}<span>Revenus attendus</span>`,
    body: `<p class="hint">Ce que tu comptes recevoir par mois. Sans saisie, le plan prend la moyenne des revenus des trois mois d'avant${!set && p.income ? ` (${m0(u(p.income))} ${base()})` : ""}.</p>
      <label class="field" for="inc-input">Par mois, en ${base()}
        <input id="inc-input" inputmode="decimal" value="${esc(sh.tmp)}" placeholder="moyenne" autocomplete="off" data-autofocus></label>
      ${sh.bad || sh.err ? `<div class="err" role="alert">${esc(sh.bad || sh.err)}</div>` : ""}
      ${set ? `<button class="link-row" type="button" data-a="binc-avg">Revenir à la moyenne des trois mois${ic("chev")}</button>` : ""}`,
    foot: `<button class="primary" type="button" data-a="binc-save" ${sh.busy || sh.bad || !(Number(sh.tmp) > 0) ? "disabled" : ""}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  if (e.target.id !== "inc-input" || SH.kind !== "bincome") return;
  const r = parseAmount(e.target.value);
  SH.bad = r.error || "";
  SH.tmp = r.value ?? "";
  renderSheet();
});

// --- reprendre un dépassement -----------------------------------------------------------------

function donors(b, cat) {
  return b.lines.filter((l) => l.group !== "fixed" && l.target && !l.yearly && l.category !== cat && u(l.target) - u(l.spent) >= 1)
    .map((l) => ({ id: l.category, name: l.name, group: l.group, rest: Math.floor(u(l.target) - u(l.spent)), proj: l.projected ? u(l.projected) : null, t: u(l.target) }))
    .sort((x, y) => y.rest - x.rest);
}
const needOf = (l) => Math.max(1, Math.ceil(u(l.spent) - u(l.target)));

SHEETS.bmove = (cat, sh) => {
  const b = cur();
  const from = b ? b.lines.find((l) => l.category === cat) : null;
  if (!from || !from.target) return { title: "Reprendre", body: skel("block") };
  const need = needOf(from), ds = donors(b, cat);
  if (!sh.tmp) {
    sh.tmp = {};
    let k = need;
    for (const d of ds) {
      if (k <= 0) break;
      const v = Math.min(k, d.rest);
      sh.tmp[d.id] = v;
      k -= v;
    }
  }
  const tot = Object.values(sh.tmp).reduce((t, v) => t + v, 0);
  const rows = ds.map((d) => {
    const v = sh.tmp[d.id] || 0, risky = v && d.proj != null && d.proj > d.t - v;
    return `<button class="mv-row${v ? " on" : ""}" type="button" data-a="bmv-pick" data-v="${esc(d.id)}" aria-pressed="${v > 0}">${catMark(d.id, d.group, "sm")}
      <span class="up-main"><b>${esc(d.name)}</b><span>reste ${m0(d.rest)}${risky ? ' · <span class="bh-bad">risque de manquer d\'ici la fin du mois</span>' : ""}</span></span>
      <span class="num mv-v">${v ? `−${m0(v)}` : "—"}</span></button>`;
  }).join("");
  return {
    title: `${catMark(cat, from.group)}<span>Reprendre pour ${esc(from.name)}</span>`,
    body: `<p class="hint">Il manque <b class="num">${m0(need)} ${base()}</b>. Le montant pris ici augmente la cible de ${esc(from.name)} et baisse celle d'où il vient, pour ce mois seulement.</p>
      ${rows || '<div class="empty">Aucune catégorie n\'a de marge ce mois-ci.</div>'}
      <div class="mv-sum"><span>Repris</span><b class="num${tot < need ? " neg" : ""}">${m0(tot)} / ${m0(need)} ${base()}</b></div>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="bmv-save" ${tot && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : `Déplacer ${m0(tot)} ${base()} avec Face ID`}</button>`,
  };
};

/** @param {[string, Record<string, unknown>][]} items @param {string} done */
async function send(items, done) {
  SH.busy = true;
  SH.err = "";
  renderSheet();
  try {
    const [text, bad] = outcome(await proposeAndApprove(items));
    if (bad) SH.err = text;
    else {
      closeSheet();
      store.invalidate();
      toast(done);
    }
  } catch (err) {
    SH.err = failure(err);
  } finally {
    SH.busy = false;
    if (SH.kind) renderSheet();
  }
}

export const actions = {
  bhead: () => {
    store.use(`/finance/flows?month=${P.month}&period=${P.period}`);
    openSheet("bhead");
  },
  bincome: () => {
    store.use(`/finance/budget?month=${store.today}&period=m`);
    openSheet("bincome");
  },
  "binc-save": () => send([["set_plan_income", { amount_minor: toMinor(Number(SH.tmp)) }]], "Revenus attendus enregistrés"),
  "binc-avg": () => send([["set_plan_income", { amount_minor: null }]], "Le plan reprend la moyenne des trois mois"),
  bmove: (cat) => openSheet("bmove", cat),
  "bmv-pick": (id) => {
    const b = cur(), from = b && b.lines.find((l) => l.category === SH.arg);
    if (!from) return;
    if (SH.tmp[id]) delete SH.tmp[id];
    else {
      const d = donors(b, SH.arg).find((x) => x.id === id), have = Object.values(SH.tmp).reduce((t, v) => t + v, 0);
      if (d) SH.tmp[id] = Math.max(1, Math.min(d.rest, needOf(from) - have));
    }
    renderSheet();
  },
  "bmv-save": () => {
    const picked = Object.entries(SH.tmp).filter(([, v]) => v > 0);
    if (!picked.length) return;
    const items = picked.map(([id, v]) => ["move_budget", { from_category: id, to_category: SH.arg, amount_minor: toMinor(v), month: P.month }]);
    return send(items, "Cibles déplacées pour ce mois");
  },
};
