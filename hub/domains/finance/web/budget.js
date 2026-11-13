// Budget : reste à vivre et rythme du mois, projection et taux d'épargne ; une section
// Catégories (variables d'abord, les dépassements en tête, puis les fixes repliées) ; le
// diagramme de flux (revenus → usage → postes), toujours ouvert ; abonnements et tendance sur
// six mois, repliés sur une ligne de résumé. Les montants, le rythme, l'état et la projection
// viennent de /finance/budget, /flows, /budget/months (audit M3) : ici on met en mots, on ne
// calcule pas.
import { go, reveal } from "../../shell.js";
import { MOIS, base, date, monthName, toMinor, units } from "../../format.js";
import { categories, foldHead, offTarget, shortMonth, trend } from "./bviews.js";
import { catState, model, yearState } from "./bmodel.js";
import { sankeyData, sankeyInfo, sankeySvg } from "./bflow.js";
import { GROUP_LABEL, catLook, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { monthStartDay, shiftMonth, store } from "../../store.js";
import {
  SHEETS, SH, amount, amount2, announce, closeSheet, esc, failure, fill, ibox, ic, money, n0, nf, openSheet, pf, pref,
  renderSheet, setPref, skel, toast,
} from "../../ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const CADENCE = { weekly: "chaque semaine", monthly: "mensuel", quarterly: "trimestriel", yearly: "annuel" };
const OLDEST = 36; // mois en arrière au plus
const B = { sk: null, bgroup: null, offOpen: false };

export const budgetPath = (month, period) => `/finance/budget?month=${month}&period=${period}`;
const flowsPath = () => `/finance/flows?month=${P.month}&period=${P.period}`;
const monthsPath = () => `/finance/budget/months?month=${P.month}&months=6`;
const recurringPath = "/finance/recurring";
const trendPath = (cat) => `/finance/trend?category=${encodeURIComponent(cat)}&months=6&month=${P.month}`;
const u = (m) => (m ? units(m) : 0);

// des écritures en devise sans change ce jour-là : laissées de côté par le serveur, dites ici
function missingFx(items) {
  if (!items.length) return "";
  const n = items.reduce((t, x) => t + x.count, 0);
  const ccys = [...new Set(items.map((x) => x.currency))].join(", ");
  return `<div class="status warn">${ic("alert")}<span>${n} écriture${n > 1 ? "s" : ""} en ${esc(ccys)} sans taux de change ce jour-là : pas comptée${n > 1 ? "s" : ""} ici tant que le cours manque.</span></div>`;
}

// dates d'une période dont le mois ne commence pas le 1er : « 25 sept. – 24 oct. »
function spanLabel(b) {
  const last = new Date(Date.parse(`${b.end}T00:00:00Z`) - 864e5);
  const first = new Date(`${b.start}T00:00:00Z`);
  return `${first.getUTCDate()} ${MOIS[first.getUTCMonth()]} – ${last.getUTCDate()} ${MOIS[last.getUTCMonth()]}`;
}

function periodLabel(b) {
  if (P.period === "m") return monthName(P.month);
  const ms = b ? b.months : [shiftMonth(P.month, -3), shiftMonth(P.month, -1)];
  return `${shortMonth(ms[0])} – ${shortMonth(ms[ms.length - 1])} ${ms[ms.length - 1].slice(0, 4)}`;
}

// --- rendu ------------------------------------------------------------------------------------

export function render() {
  const be = store.use(budgetPath(P.month, P.period));
  const b = be.data;
  const fe = store.use(flowsPath());
  const me = store.use(monthsPath());
  const re = store.use(recurringPath);
  const lab = periodLabel(b);
  const oldest = shiftMonth(store.today, -OLDEST);
  fill($("budCtx"), `<div class="stepper" role="group" aria-label="Mois affiché">
      <button type="button" data-a="bm" data-v="-1" aria-label="Mois précédent" ${P.month <= oldest ? "disabled" : ""}>${ic("back")}</button>
      <b aria-live="polite">${esc(lab)}${b && monthStartDay() !== 1 ? `<small class="per-dates">${esc(spanLabel(b))}</small>` : ""}</b>
      <button type="button" data-a="bm" data-v="1" aria-label="Mois suivant" ${P.month >= store.today ? "disabled" : ""}>${ic("chev")}</button></div>
    <div class="seg small" role="group" aria-label="Période"><button type="button" data-a="bper" data-v="m" aria-pressed="${P.period === "m"}">Mois</button><button type="button" data-a="bper" data-v="q" aria-pressed="${P.period === "q"}" aria-label="Trois mois complets avant le mois choisi">3 mois</button></div>`);
  if (be.status === "error") return fill($("budBody"), `<div class="err-box" role="alert">Impossible de charger le budget : ${esc(be.error.message)}</div>`);
  if (!b) return fill($("budBody"), skel());
  const m = model(b);
  const st = m.state, off = offTarget(m);
  let proj = "";
  if (m.projection != null && m.T != null) {
    const d = m.projection - m.T;
    proj = `<div class="proj">${ic("trend")}<span>Projection fin ${P.period === "m" ? monthName(P.month).split(" ")[0] : "de période"} : <b class="num">${amount(m.projection)}</b>, ${d > 0 ? `<b>${n0(d)} au-dessus</b>` : `<span class="delta pos">${n0(-d)} sous</span>`} le budget</span></div>`;
  }
  const hero = `<section class="card bflat" aria-labelledby="t-bud">
      <div class="hero-label"><span id="t-bud">${m.T == null ? "Dépensé" : P.period === "m" ? "Reste à vivre" : "Reste sur 3 mois"}</span><span>${!m.current ? "clos" : m.daysLeft < 1 ? "Dernier jour du mois" : `${m.daysLeft} jour${m.daysLeft > 1 ? "s" : ""} restant${m.daysLeft > 1 ? "s" : ""}`}</span></div>
      <div class="hero-amount num${m.rest != null && m.rest < 0 ? " neg" : ""}"><span class="money">${nf(m.T == null ? m.spent : m.rest)}</span><small>${base()}</small></div>
      ${m.T == null ? `<button class="primary plan-cta" type="button" data-a="plan" aria-haspopup="dialog">${ic("wallet")}Créer mon budget</button>` : `<div class="hint">${amount(m.spent)} dépensés sur ${amount(m.T)} de budget${off >= 1 ? `, dont ${n0(off)} hors cible` : ""}</div>
      <div class="pbar" role="img" aria-label="${pf(m.ratio, 0)} % du budget dépensé${m.expected != null ? `, ${pf(m.expected, 0)} % attendus à ce jour` : ""}" data-css="--c:${st.color}"><i data-css="width:${Math.min(100, m.ratio * 100).toFixed(1)}%"></i>${m.expected != null ? `<span class="pace" data-css="left:${(m.expected * 100).toFixed(1)}%"></span>` : ""}</div>`}
      <div class="status ${st.k}">${ic(st.icon)}<span>${st.text}</span></div>
      ${missingFx(m.missingFx)}
      ${fe.data ? savingsStrip(fe.data) : ""}
      ${proj}
    </section>`;
  // flux
  let flow = "";
  if (fe.data) {
    const sd = sankeyData(fe.data);
    if (B.sk && ![...sd.srcs, ...sd.mids, ...sd.mids.flatMap((x) => x.kids)].some((n) => n.id === B.sk)) B.sk = null;
    const spentF = sd.out - sd.S;
    flow = `<section class="card bflat" aria-labelledby="t-flow">
      <div class="section-head"><h2 class="section-title" id="t-flow">Où va l'argent</h2></div>
      <p class="hint">Entré ${amount(sd.I)} · dépensé ${amount(spentF)} · épargné ${amount(sd.S)}</p>
      ${sd.tot > 1 ? `<div class="skcols" aria-hidden="true"><span>Revenus</span><span>Usage</span><span>Postes</span></div>${sankeySvg(sd, B.sk)}${sankeyInfo(sd, B.sk)}` : '<div class="empty">Aucun mouvement sur la période.</div>'}
    </section>`;
  } else if (fe.status === "error") flow = `<div class="err-box">Flux indisponible : ${esc(fe.error.message)}</div>`;
  fill($("budBody"), hero + categories(m, B, fe.data) + flow + subscriptions(re) + trend(me.data, P) + '<div class="endspace"></div>');
}

// revenus, épargne et taux d'épargne de la période, sous le reste à vivre
function savingsStrip(f) {
  const I = u(f.income), S = u(f.groups.find((x) => x.group === "savings")?.total);
  return `<div class="strip three"><div><span>Revenus</span><b class="num">${money(I)}</b></div><div><span>Épargné</span><b class="num">${money(S)}</b></div><div><span>Taux d'épargne</span><b class="num">${I ? `${pf(S / I, 0)} %` : "—"}</b></div></div>`;
}

function subscriptions(re) {
  const r = re.data;
  const items = r && r.items ? r.items.filter((x) => x.active) : [];
  if (!items.length) return "";
  const open = pref("subsOpen", false);
  const total = r.monthly_total.map((x) => `${n0(Math.abs(u(x)))} ${x.currency}`).join(" + ");
  const next = items.slice().sort((a, b) => (a.next_date || "").localeCompare(b.next_date || ""))[0];
  const ups = items.filter((s) => Math.abs(u(s.last_amount)) - Math.abs(u(s.amount)) > 0.009).length;
  const sum = `${items.length} abonnement${items.length > 1 ? "s" : ""} · ${esc(total)} par mois${next ? ` · prochain : ${esc(next.label)} le ${date(next.next_date)}` : ""}${ups ? ` · ${ups} en hausse` : ""}`;
  return `<section class="card${open ? "" : " folded"}" id="subs" aria-labelledby="t-subs">
      ${foldHead("subs", "Abonnements", open, sum)}
      ${open ? `<div class="sec-body" id="subs-body">${items.map((s) => {
        const up = Math.abs(u(s.last_amount)) - Math.abs(u(s.amount));
        return `<div class="kv">${ibox(ic("repeat"), "var(--s4)", "sm")}<span>${esc(s.label)}<span class="s">${CADENCE[s.cadence] || esc(s.cadence)} · prochain le ${date(s.next_date)}</span>${up > 0.009 ? ` <span class="pill warn">${ic("alert")}hausse +${amount2(up)}</span>` : ""}</span><b class="num">${amount2(Math.abs(u(s.last_amount)))}${s.amount.currency === base() ? "" : ` ${esc(s.amount.currency)}`}</b></div>`;
      }).join("")}<p class="hint">Paiements réguliers repérés dans le registre ; les prochaines échéances sont estimées.</p></div>` : ""}
    </section>`;
}

// --- panneau d'une catégorie ------------------------------------------------------------------

SHEETS.cat = (id, sh) => {
  const b = store.data(budgetPath(P.month, P.period));
  const cats = store.data("/finance/categories");
  const c = cats ? cats.items.find((x) => x.id === id) : null;
  const l = b ? b.lines.find((x) => x.category === id) : null;
  if (!c && !l) return { title: "Catégorie", body: skel("block") };
  const name = c ? c.name : l.name, group = c ? c.group : l.group;
  const m = b ? model(b) : null;
  const line = m ? m.lines.find((x) => x.category === id) : null;
  const spent = line ? line.s : 0;
  const n = P.period === "q" ? 3 : 1;
  const year = line && line.yearly ? (line.yearly.target ? u(line.yearly.target) : null) : null;
  const target = line && line.yearly ? (year != null ? year / 12 : null) : line && line.t != null ? line.t / n : null; // cible mensuelle
  if (sh.cad == null) sh.cad = line && line.yearly ? "year" : "month";
  if (sh.tmp == null) sh.tmp = sh.cad === "year" ? Math.round(year || 0) : target != null ? Math.round(target) : 0;
  const was = line && line.yearly ? "year" : "month";
  const shown = was === "year" ? Math.round(year ?? -1) : Math.round(target ?? -1);
  const s = line ? (line.yearly ? yearState(line) : catState(line)) : { k: "ok", txt: "Aucune dépense" };
  const te = store.use(trendPath(id));
  let hist = skel("block");
  if (te.data) {
    const pts = te.data.series.map((x) => ({ m: x.month, v: Math.abs(u(x.total)) }));
    const mx = Math.max(1, ...pts.map((p) => p.v), target || 0) * 1.1;
    const look = catLook(id, group);
    hist = `<div class="mini-months" role="img" aria-label="${pts.map((p) => `${monthName(p.m).split(" ")[0]} ${n0(p.v)}`).join(", ")}${target != null ? `, cible ${n0(target)}` : ""}">
      ${target != null ? `<span class="tline" data-css="--b:${(18 + (target / mx) * 72).toFixed(0)}px"></span>` : ""}
      ${pts.map((p) => `<div><i class="${p.m === P.month ? "" : "past"}" data-css="--h:${((p.v / mx) * 72).toFixed(0)}px;--c:${target != null && p.v > target ? "var(--neg)" : look.color}"></i><span>${shortMonth(p.m)}</span></div>`).join("")}</div>
      ${target != null ? '<p class="hint">Pointillés : la cible mensuelle.</p>' : ""}`;
  }
  const budgetable = group === "fixed" || group === "variable";
  const removing = budgetable && !(sh.tmp > 0) && shown > 0, changed = removing || (budgetable && sh.tmp > 0 && (sh.tmp !== shown || sh.cad !== was)); // champ vidé : cible retirée
  const per = sh.cad === "year" ? "annuelle" : "mensuelle";
  return {
    title: `${catMark(id, group)}<span>${esc(name)}</span>`,
    body: `<div class="sheet-big num">${amount(spent)}${line && line.t != null ? ` <small>sur ${amount(line.t)}</small>` : ""}</div>
      <span class="crow-st ${s.k}">${esc(s.txt)} · ${esc(periodLabel(b))}</span>
      <h3>Six derniers mois</h3>${hist}
      ${budgetable ? `<h3>Cible ${per}</h3>
      <div class="seg cad-seg" role="group" aria-label="Suivi">${[["month", "Par mois"], ["year", "Par an"]].map(([k, l]) => `<button type="button" data-a="tcad" data-v="${k}" aria-pressed="${sh.cad === k}">${l}</button>`).join("")}</div>
      <div class="target"><button type="button" data-a="tstep" data-v="-10" aria-label="Diminuer de 10">−</button><input id="t-input" inputmode="numeric" value="${sh.tmp || ""}" aria-label="Cible ${per} en ${base()}" placeholder="aucune"><button type="button" data-a="tstep" data-v="10" aria-label="Augmenter de 10">+</button></div>
      ${sh.cad === "year" ? `<p class="hint">Pour les dépenses par à-coups (vacances, entretien) : comparée au cumul depuis janvier, sans peser sur le reste à vivre du mois.${line && line.yearly ? ` Dépensé depuis janvier : ${n0(u(line.yearly.spent))} ${base()}.` : ""}</p>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}` : '<p class="hint">Les cibles portent sur les dépenses fixes et variables.</p>'}
      ${line && line.count ? `<div class="stack-v"><button class="secondary" type="button" data-a="cat-tx" data-v="${esc(id)}">${ic("list")}${line.count > 1 ? `Voir les ${line.count} écritures` : "Voir l'écriture"}</button></div>` : ""}`,
    foot: budgetable ? `<button class="primary" type="button" data-a="target-save" ${changed && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : removing ? "Retirer la cible avec Face ID" : "Enregistrer la cible avec Face ID"}</button>` : "",
  };
};

// --- préparer le budget : une cible par catégorie de dépense, proposée d'après les 3 derniers mois

const CATS = "/finance/categories";
const roundUp = (v) => (v > 0 ? Math.ceil(v / 10) * 10 : 0);

function planData() {
  const cur = store.data(budgetPath(store.today, "m")), past = store.data(budgetPath(store.today, "q")), cats = store.data(CATS);
  if (!cur || !past || !cats) return null;
  // une catégorie suivie à l'année se règle en montant annuel
  const year = new Set(cur.lines.filter((l) => l.yearly).map((l) => l.category));
  const now = Object.fromEntries(cur.lines.map((l) => [l.category, l.yearly ? (l.yearly.target ? u(l.yearly.target) : null) : l.target ? u(l.target) : null]));
  const avg = Object.fromEntries(past.lines.map((l) => [l.category, (u(l.spent) / past.months.length) * (year.has(l.category) ? 12 : 1)]));
  const rows = cats.items.filter((c) => c.active && (c.group === "fixed" || c.group === "variable"))
    .map((c) => ({ id: c.id, name: c.name, group: c.group, now: now[c.id] ?? null, avg: avg[c.id] || 0, year: year.has(c.id) }))
    .sort((a, b) => (a.group === b.group ? 0 : a.group === "fixed" ? -1 : 1) || b.avg - a.avg || a.name.localeCompare(b.name, "fr"));
  return { rows, income: u(past.income) / past.months.length, months: past.months };
}

const planChanges = (d, tmp) => d.rows.filter((r) => tmp[r.id] != null && tmp[r.id] !== (r.now ?? 0) && !(r.now == null && tmp[r.id] === 0));

SHEETS.plan = (_arg, sh) => {
  const d = planData();
  if (!d) return { title: "Préparer le budget", body: skel("block") };
  if (!sh.tmp) sh.tmp = Object.fromEntries(d.rows.map((r) => [r.id, r.now ?? roundUp(r.avg)]));
  const total = d.rows.reduce((t, r) => t + (sh.tmp[r.id] || 0) / (r.year ? 12 : 1), 0);
  const ch = planChanges(d, sh.tmp);
  const from = `${shortMonth(d.months[0])} – ${shortMonth(d.months[d.months.length - 1])}`;
  let g = null;
  const rows = d.rows.map((r) => {
    const head = r.group !== g ? `<div class="grp"><span>${GROUP_LABEL[r.group]}</span></div>` : "";
    g = r.group;
    const v = sh.tmp[r.id];
    return `${head}<div class="plan-row">${catMark(r.id, r.group, "sm")}
      <label for="plan-${esc(r.id)}"><b>${esc(r.name)}${r.year ? ' <span class="pill">par an</span>' : ""}</b><small>${r.avg ? `moyenne ${n0(r.avg)}` : "rien dépensé"}${r.now != null ? ` · cible ${n0(r.now)}` : ""}</small></label>
      <input id="plan-${esc(r.id)}" data-plan="${esc(r.id)}" inputmode="numeric" value="${v ? v : ""}" placeholder="—" aria-label="Cible ${r.year ? "annuelle" : "mensuelle"} ${esc(r.name)} en ${base()}"></div>`;
  }).join("");
  return {
    title: "Préparer le budget",
    body: `<p class="hint">Une cible par mois et par catégorie, proposée d'après ta moyenne des derniers mois (${esc(from)}) et arrondie à la dizaine. Laisse vide ce que tu ne veux pas suivre.</p>
      <div class="plan-sum"><span>Revenus<b class="num">${amount(d.income)}</b></span><span>Budget<b class="num">${amount(total)}</b></span><span>Reste<b class="num${d.income - total < 0 ? " neg" : ""}">${amount(d.income - total)}</b></span></div>
      ${rows}${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="plan-save" ${ch.length && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : ch.length ? `Enregistrer ${ch.length} cible${ch.length > 1 ? "s" : ""} avec Face ID` : "Aucun changement"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  const id = e.target.dataset && e.target.dataset.plan;
  if (!id || SH.kind !== "plan" || !SH.tmp) return;
  const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
  SH.tmp[id] = Number.isNaN(n) ? 0 : n;
  renderSheet();
});

document.addEventListener("input", (e) => {
  if (e.target.id !== "t-input" || SH.kind !== "cat") return;
  const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
  SH.tmp = Number.isNaN(n) ? 0 : n;
  renderSheet();
});

function setMonth(month) {
  if (month > store.today || month < shiftMonth(store.today, -OLDEST)) return;
  B.sk = null;
  store.set({ month });
  announce(P.period === "m" ? monthName(month) : periodLabel(null));
}

export const actions = {
  cat: (id) => {
    if (P.tab !== "budget") {
      store.set({ month: store.today, period: "m" });
      go("budget");
    }
    store.use("/finance/categories");
    openSheet("cat", id);
  },
  bm: (v) => setMonth(shiftMonth(P.month, Number(v))),
  bper: (v) => {
    B.sk = null;
    store.set({ period: v });
  },
  month: (v) => {
    B.sk = null;
    store.set({ month: v, period: "m" });
    window.scrollTo({ top: 0, behavior: "smooth" });
    announce(monthName(v));
  },
  sk: (v) => {
    B.sk = !v || B.sk === v ? null : v;
    store.notify();
  },
  "sk-list": (g) => {
    B.bgroup = g;
    store.notify();
    requestAnimationFrame(() => reveal($("budCats")));
  },
  bgroupx: () => {
    B.bgroup = null;
    store.notify();
  },
  bfold: (k) => {
    const key = `${k}Open`;
    setPref(key, !pref(key, false));
    store.notify();
  },
  boff: () => {
    B.offOpen = !B.offOpen;
    store.notify();
  },
  bfixed: () => {
    setPref("fixedOpen", !pref("fixedOpen", false));
    store.notify();
  },
  subs: () => {
    setPref("subsOpen", true);
    store.set({ month: store.today, period: "m" });
    go("budget");
    requestAnimationFrame(() => requestAnimationFrame(() => reveal($("subs"))));
  },
  tcad: (k) => {
    if (SH.cad === k) return;
    // la même enveloppe, exprimée par an ou par mois
    SH.tmp = k === "year" ? (SH.tmp || 0) * 12 : Math.round((SH.tmp || 0) / 12);
    SH.cad = k;
    renderSheet();
  },
  tstep: (v) => {
    SH.tmp = Math.max(0, (SH.tmp || 0) + Number(v));
    renderSheet();
  },
  plan: () => {
    for (const p of [budgetPath(store.today, "m"), budgetPath(store.today, "q"), CATS]) store.use(p);
    openSheet("plan");
  },
  "plan-save": async () => {
    const d = planData();
    if (!d) return;
    const ch = planChanges(d, SH.tmp);
    if (!ch.length) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const items = ch.map((r) => ["set_budget", { category_id: r.id, amount_minor: toMinor(SH.tmp[r.id]), cadence: r.year ? "year" : "month", valid_from: `${store.today}-01` }]);
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(`${ch.length} cible${ch.length > 1 ? "s" : ""} enregistrée${ch.length > 1 ? "s" : ""}`);
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "target-save": async () => {
    const id = SH.arg, value = SH.tmp, yearly = SH.cad === "year";
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove([["set_budget", { category_id: id, amount_minor: toMinor(value), cadence: yearly ? "year" : "month" }]]));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(value > 0 ? `Cible enregistrée : ${n0(value)} ${base()} par ${yearly ? "an" : "mois"}` : "Cible retirée");
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
  "cat-tx": (id) => {
    closeSheet(true);
    const months = P.period === "m" ? [P.month] : (store.data(budgetPath(P.month, P.period))?.months || [P.month]);
    store.set({ tx: "all", q: "", txcat: { id, from: months[0], to: months[months.length - 1] } });
    go("journal", { top: true });
  },
};

