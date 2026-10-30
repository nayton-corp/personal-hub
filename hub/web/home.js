// Bloc d'accueil de la finance : le bilan du mois passé les premiers jours, deux tuiles
// (patrimoine, reste à vivre), en tête de l'accueil ; ses lignes « À faire » et « À savoir »
// rejoignent celles des autres domaines (accueil.js).
import { hiddenIds } from "./accounts.js";
import { budgetPath, model } from "./budget.js";
import { go } from "./shell.js";
import { base, date, monthName } from "./format.js";
import { catMark, taxRate } from "./meta.js";
import { shiftMonth, store } from "./store.js";
import { esc, fill, ic, n0, nf, pctOnly, pf, pref, setPref, sgn, skel } from "./ui.js";
import * as wealth from "./wealth.js";

const STALE_DAYS = 45;
const RESERVE_MONTHS = 6;
const BILAN_DAYS = 7; // le bilan du mois passé reste sur l'accueil la première semaine
const kpisPath = () => `/finance/kpis?month=${store.today}`;
const alertsPath = "/observations?domain=finance"; // les constats des sentinelles
const connPath = "/collectors/connections";

function sparkPath(k) {
  if (!k) return null;
  const d = new Date(`${k.as_of}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 30);
  return `/finance/performance?from=${d.toISOString().slice(0, 10)}&step=day`;
}

function spark(vals, w = 140, h = 30) {
  if (vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals), d = mx - mn || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, 3 + (h - 6) * (1 - (v - mn) / d)]);
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="M${pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join("L")}"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3"/></svg>`;
}

export const lead = true;

// les lignes de la finance pour « À faire » et « À savoir » ; null tant que les chiffres manquent
export function rows() {
  const k = store.data(kpisPath());
  if (!k) return null;
  const out = [];
  // à faire : ce qui se règle d'un geste
  if (k.to_categorize > 0) out.push({ ic: "help", c: "var(--accent)", t: `${k.to_categorize} écriture${k.to_categorize > 1 ? "s" : ""} à classer`, s: "Par contrepartie, en un Face ID", a: "gotodo" });
  const cs = store.data(connPath);
  const missing = cs ? cs.items.filter((c) => !c.ready) : [];
  if (missing.length) out.push({ ic: "key", c: "var(--s3)", t: `${missing.length} connexion${missing.length > 1 ? "s" : ""} à régler`, s: `${missing.map((c) => c.label).join(", ")} : identifiants à donner`, a: "rubric", v: "conn" });
  if (k.stale_accounts > 0) out.push({ ic: "clock", c: "var(--s3)", t: `${k.stale_accounts} compte${k.stale_accounts > 1 ? "s" : ""} à rafraîchir`, s: `Dernière donnée il y a plus de ${STALE_DAYS} jours`, a: "rubric", v: "accounts" });
  // à savoir : dépassements, hausses, marge 3a, réserve
  const b = store.data(budgetPath(store.today, "m"));
  for (const l of b ? b.lines.filter((x) => x.over).sort((x, y) => Number(y.ratio) - Number(x.ratio)) : []) {
    const y = l.yearly, spent = (y ? y.spent : l.spent).minor / 100, target = (y ? y.target : l.target).minor / 100;
    out.push({ info: true, mark: catMark(l.category, l.group), t: `${l.name} dépasse de ${n0(spent - target)} ${base()}`, s: `${n0(spent)} sur ${n0(target)}${y ? " depuis janvier" : " ce mois"}`, a: "cat", v: l.category });
  }
  if (k.unmatched_transfers > 0) out.push({ info: true, ic: "swap", c: "var(--s6)", t: `${k.unmatched_transfers} virement${k.unmatched_transfers > 1 ? "s" : ""} sans autre côté`, s: "Un relevé manque peut-être sur l'autre compte", a: "rubric", v: "accounts" });
  const alerts = store.data(alertsPath);
  for (const a of alerts ? alerts.items : []) {
    // les dépassements viennent déjà du budget ci-dessus, la marge 3a des chiffres clés
    if (a.kind === "pillar3a_margin" || a.kind === "budget_over") continue;
    const d = a.detail;
    const s = a.kind === "recurring_up"
      ? `${amount2Text(d.usual)} → ${amount2Text(d.last)} ${d.last.currency} · le ${date(a.on_date)}`
      : `${n0(d.spent.minor / 100)} sur ${n0(d.target.minor / 100)} ${base()}${a.kind === "budget_likely" ? ` · ${n0(d.projected.minor / 100)} projetés` : ""}`;
    const cat = a.kind === "recurring_up" ? null : d.category;
    out.push({ info: true, ic: a.kind === "recurring_up" ? "repeat" : "alert", c: a.kind === "recurring_up" ? "var(--s4)" : "var(--s3)", mark: cat ? catMark(cat) : null, t: a.title, s, a: a.kind === "recurring_up" ? "subs" : cat ? "cat" : "tab", v: cat || "budget" });
  }
  const p3 = k.pillar3a;
  if (p3 && p3.margin.minor > 0) {
    const m = p3.margin.minor / 100;
    out.push({ info: true, ic: "piggy", c: "var(--s1)", t: `Marge 3a ${p3.year} : ${n0(m)} ${base()}`, s: `Jusqu'au 31 décembre · environ ${n0(m * taxRate())} ${base()} d'impôt en moins`, a: "ret3a" });
  }
  const cover = k.months_covered == null ? null : Number(k.months_covered);
  if (cover != null) {
    const liquid = k.liquid.minor / 100, avg = cover > 0 ? liquid / cover : 0, extra = liquid - RESERVE_MONTHS * avg;
    const s = cover < 3 ? `Moins de 3 mois : à renforcer avant d'investir` : extra > 0 && cover > RESERVE_MONTHS ? `Environ ${n0(extra)} ${base()} au-delà de ${RESERVE_MONTHS} mois, sur des comptes à presque 0 %` : `Entre 3 et ${RESERVE_MONTHS} mois : la zone conseillée`;
    out.push({ info: true, ic: "shield", c: cover < 3 ? "var(--neg)" : "var(--s2)", t: `Réserve : ${cover.toFixed(1).replace(".", ",")} mois de dépenses`, s, a: "w-only", v: "cat|cash" });
  }
  return out;
}

// premiers jours du mois budgétaire : le mois d'avant en trois chiffres, une fois par mois
function bilan(cur) {
  if (!cur || cur.days_left == null) return "";
  const days = Math.round((Date.parse(`${cur.end}T00:00:00Z`) - Date.parse(`${cur.start}T00:00:00Z`)) / 864e5);
  if (days - cur.days_left > BILAN_DAYS) return "";
  const prev = shiftMonth(store.today, -1);
  if (pref(`bilan-${prev}`, false)) return "";
  const pb = store.use(budgetPath(prev, "m")).data;
  const pf2 = store.use(`/finance/flows?month=${prev}&period=m`).data;
  if (!pb || !pf2) return "";
  const m = model(pb, false);
  const I = pf2.income.minor / 100, S = (pf2.groups.find((x) => x.group === "savings")?.total.minor || 0) / 100;
  const over = m.lines.filter((l) => l.over).length;
  const name = monthName(prev).split(" ")[0];
  const res = m.T == null ? `${n0(m.spent)} ${base()} dépensés` : m.rest >= 0 ? `${n0(m.rest)} ${base()} sous le budget` : `${n0(-m.rest)} ${base()} au-dessus du budget`;
  return `<section class="card bilan" aria-labelledby="t-bilan">
    <div class="section-head"><h2 class="section-title" id="t-bilan">Bilan ${name.startsWith("a") || name.startsWith("o") ? "d'" : "de "}${esc(name)}</h2><button class="icon-btn" type="button" data-a="bilan-x" data-v="${prev}" aria-label="Masquer le bilan">${ic("close")}</button></div>
    <div class="strip three"><div><span>Budget</span><b class="${m.T != null && m.rest < 0 ? "neg" : "pos"}">${esc(res)}</b></div><div><span>Épargné</span><b class="num"><span class="money">${n0(S)}</span>${I > 0 ? ` · ${pf(S / I, 0)} %` : ""}</b></div><div><span>Dépassements</span><b>${over ? `${over} catégorie${over > 1 ? "s" : ""}` : "aucun"}</b></div></div>
    <button class="link-row" type="button" data-a="bilan-go" data-v="${prev}">Revoir ${esc(name)} dans le budget${ic("chev")}</button>
  </section>`;
}

const amount2Text = (m) => Math.abs(m.minor / 100).toFixed(2);

export function render(box) {
  const ke = store.use(kpisPath());
  const k = ke.data;
  store.use(alertsPath);
  store.use(connPath);
  const be = store.use(budgetPath(store.today, "m"));
  const sp = sparkPath(k);
  const se = sp ? store.use(sp) : null;
  if (ke.status === "error") {
    fill(box, `<div class="err-box" role="alert">Impossible de charger l'accueil : ${esc(ke.error.message)}</div>`);
    return;
  }
  if (!k) {
    fill(box, skel());
    return;
  }
  // un compte masqué sort aussi du patrimoine de l'accueil
  store.use("/finance/accounts");
  const hidden = hiddenIds();
  // courbe et rendement sans les comptes masqués ; le rendement ne compte pas les versements
  const sum30 = se && se.data ? se.data.summary : null;
  const vals = sum30 ? se.data.items.map((i) => i.value.minor / 100) : [];
  const net = hidden.size && vals.length ? vals[vals.length - 1] : k.net_worth.minor / 100;
  const p30 = sum30 && sum30.twr != null ? Number(sum30.twr) : null;
  const g30 = sum30 ? sum30.gain.minor / 100 : null;
  const m = be.data ? model(be.data, true) : null;
  let budgetTile;
  if (!m) budgetTile = `<span class="tile-lbl">${ic("wallet")}Reste à vivre</span>${skel("block")}`;
  else if (m.T == null) {
    budgetTile = `<span class="tile-lbl">${ic("wallet")}Dépensé ce mois</span>
      <span class="tile-amt num"><span class="money">${n0(m.spent)}</span></span>
      <span class="tile-sub">Pas encore de budget</span>`;
  } else {
    const st = m.state;
    budgetTile = `<span class="tile-lbl">${ic("wallet")}Reste à vivre</span>
      <span class="tile-amt num${m.rest < 0 ? " neg" : ""}"><span class="money">${nf(m.rest)}</span></span>
      <span class="tile-sub"><span class="st-${st.k}">${st.short}</span> · ${m.daysLeft} j</span>
      <span class="pbar thin" data-css="--c:${st.color};margin-top:12px"><i data-css="width:${Math.min(100, m.ratio * 100).toFixed(1)}%"></i>${m.expected != null ? `<span class="pace" data-css="left:${(m.expected * 100).toFixed(1)}%"></span>` : ""}</span>`;
  }
  const budgetLabel = m && m.T != null ? `Reste à vivre ce mois ${nf(m.rest)} ${base()}, ${m.state.short}, ${m.daysLeft} jours restants. Ouvrir le budget` : "Ouvrir le budget";
  fill(box, `${bilan(be.data)}
    <div class="tiles">
      <button class="tile" type="button" data-a="tab" data-v="patrimoine" aria-label="Patrimoine ${n0(net)} ${base()}${g30 != null ? `, gain ${sgn(g30)}${n0(g30)} ${base()}${p30 != null ? `, rendement ${sgn(p30)}${pf(Math.abs(p30))} %` : ""} sur 30 jours` : ""}. Ouvrir le patrimoine">
        <span class="tile-lbl">${ic("trend")}Patrimoine</span>
        <span class="tile-amt num"><span class="money">${n0(net)}</span></span>
        <span class="tile-sub">${vals.length > 1 && p30 != null ? `${pctOnly(p30)} sur 30 jours` : base()}</span>
        ${spark(vals)}
      </button>
      <button class="tile" type="button" data-a="tab" data-v="budget" aria-label="${budgetLabel}">${budgetTile}</button>
    </div>`);
}

export const actions = {
  gotodo: () => {
    store.set({ tx: "todo", q: "", txcat: null });
    go("journal", { top: true });
  },
  "bilan-x": (m) => {
    setPref(`bilan-${m}`, true);
    store.notify();
  },
  "bilan-go": (m) => {
    store.set({ month: m, period: "m" });
    go("budget", { top: true });
  },
  ret3a: () => {
    wealth.only("goal", "retirement");
    go("patrimoine", { top: true });
  },
};

