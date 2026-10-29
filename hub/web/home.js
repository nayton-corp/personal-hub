// Accueil : deux tuiles (patrimoine, reste à vivre), ce qui attend une action, puis ce qui est
// bon à savoir. Chaque ligne mène à l'écran où l'on agit.
import { hiddenIds } from "./accounts.js";
import { budgetPath, model } from "./budget.js";
import { go } from "./finance.js";
import { base, date, monthName } from "./format.js";
import { catMark } from "./meta.js";
import { approve, outcome, pendingPath } from "./proposals.js";
import { api, store } from "./store.js";
import { SHEETS, closeSheet, esc, failure, fill, ibox, ic, n0, nf, openSheet, pctOnly, pf, sgn, toast } from "./ui.js";
import * as wealth from "./wealth.js";

const $ = (id) => document.getElementById(id);
const STALE_DAYS = 45;
const kpisPath = () => `/finance/kpis?month=${store.today}`;
const alertsPath = "/finance/alerts";
const connPath = "/collectors/connections";
const unchecked = new Set(); // propositions décochées dans le panneau « À valider »
let busy = false;

function sparkPath(k) {
  if (!k) return null;
  const d = new Date(`${k.as_of}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 30);
  return `/finance/networth/history?from=${d.toISOString().slice(0, 10)}&step=day`;
}

function spark(vals, w = 140, h = 30) {
  if (vals.length < 2) return "";
  const mn = Math.min(...vals), mx = Math.max(...vals), d = mx - mn || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * w, 3 + (h - 6) * (1 - (v - mn) / d)]);
  const [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="M${pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join("L")}"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3"/></svg>`;
}

function items() {
  const k = store.data(kpisPath());
  if (!k) return [];
  const out = [];
  const pending = store.data(pendingPath);
  const np = pending ? pending.items.length : 0;
  if (np) out.push({ ic: "faceid", c: "var(--accent)", t: `${np} proposition${np > 1 ? "s" : ""} à valider`, s: "Un seul Face ID pour tout le lot", a: "props" });
  const b = store.data(budgetPath(store.today, "m"));
  for (const l of b ? b.lines.filter((x) => x.over).sort((x, y) => Number(y.ratio) - Number(x.ratio)) : []) {
    const spent = l.spent.minor / 100, target = l.target.minor / 100;
    out.push({ mark: catMark(l.category, l.group), t: `${l.name} : budget dépassé`, s: `${n0(spent)} sur ${n0(target)} ${base()}, dépassé de ${n0(spent - target)}`, a: "cat", v: l.category });
  }
  if (k.to_categorize > 0) out.push({ ic: "help", c: "var(--accent)", t: `${k.to_categorize} écriture${k.to_categorize > 1 ? "s" : ""} à classer`, s: "Par contrepartie, en un Face ID", a: "gotodo" });
  const cs = store.data(connPath);
  const missing = cs ? cs.items.filter((c) => !c.ready) : [];
  if (missing.length) out.push({ ic: "key", c: "var(--s3)", t: `${missing.length} connexion${missing.length > 1 ? "s" : ""} à régler`, s: `${missing.map((c) => c.label).join(", ")} : identifiants à donner`, a: "settings" });
  if (k.stale_accounts > 0) out.push({ ic: "clock", c: "var(--s3)", t: `${k.stale_accounts} compte${k.stale_accounts > 1 ? "s" : ""} à rafraîchir`, s: `Dernier relevé de plus de ${STALE_DAYS} jours`, a: "settings" });
  // bon à savoir
  if (k.unmatched_transfers > 0) out.push({ info: true, ic: "swap", c: "var(--s6)", t: `${k.unmatched_transfers} virement${k.unmatched_transfers > 1 ? "s" : ""} sans autre côté`, s: "Un relevé manque peut-être sur l'autre compte", a: "settings" });
  const alerts = store.data(alertsPath);
  for (const a of alerts ? alerts.items : []) {
    if (a.kind === "pillar3a_margin") continue;
    const d = a.detail;
    const s = a.kind === "recurring_up"
      ? `${amount2Text(d.usual)} → ${amount2Text(d.last)} ${d.last.currency} · le ${date(a.on_date)}`
      : `${n0(d.spent.minor / 100)} sur ${n0(d.target.minor / 100)} ${base()}${a.kind === "budget_likely" ? ` · ${n0(d.projected.minor / 100)} projetés` : ""}`;
    out.push({ info: true, ic: a.kind === "recurring_up" ? "repeat" : "alert", c: a.kind === "recurring_up" ? "var(--s4)" : "var(--s3)", t: a.title, s, a: a.kind === "recurring_up" ? "subs" : "tab", v: "budget" });
  }
  const p3 = k.pillar3a;
  if (p3 && p3.margin.minor > 0) out.push({ info: true, ic: "piggy", c: "var(--s1)", t: `Marge 3a ${p3.year} : ${n0(p3.margin.minor / 100)} ${base()}`, s: `Versé ${n0(p3.paid.minor / 100)} sur ${n0(p3.cap.minor / 100)} ${base()}, jusqu'au 31 décembre`, a: "ret3a" });
  return out;
}

const amount2Text = (m) => Math.abs(m.minor / 100).toFixed(2);

export function todoCount() {
  return items().filter((x) => !x.info).length;
}

export function render() {
  const ke = store.use(kpisPath());
  const k = ke.data;
  store.use(pendingPath);
  store.use(alertsPath);
  store.use(connPath);
  const be = store.use(budgetPath(store.today, "m"));
  const sp = sparkPath(k);
  const se = sp ? store.use(sp) : null;
  const sub = $("home-sub");
  sub.classList.remove("warn");
  if (k) {
    const age = k.last_statement ? Math.floor((Date.now() - Date.parse(`${k.last_statement}T00:00:00Z`)) / 864e5) : null;
    sub.textContent = k.last_statement ? `${monthName(store.today).replace(/^./, (c) => c.toUpperCase())} · relevé du ${date(k.last_statement)}` : "Aucun relevé importé";
    if (age == null || age > STALE_DAYS) sub.classList.add("warn");
  }
  if (ke.status === "error") {
    fill($("homeBody"), `<div class="err-box" role="alert">Impossible de charger l'accueil : ${esc(ke.error.message)}</div>`);
    return;
  }
  if (!k) {
    fill($("homeBody"), '<div class="loading">Chargement…</div>');
    return;
  }
  // un compte masqué sort aussi du patrimoine de l'accueil
  store.use("/finance/accounts");
  const hidden = hiddenIds();
  const worth = (i) => (hidden.size ? Object.entries(i.by_account || {}).reduce((t, [id, v]) => t + (hidden.has(id) ? 0 : v.minor), 0) : i.net_worth.minor) / 100;
  const vals = se && se.data ? se.data.items.map(worth) : [];
  const net = hidden.size && vals.length ? vals[vals.length - 1] : k.net_worth.minor / 100;
  const p30 = vals.length > 1 && vals[0] ? vals[vals.length - 1] / vals[0] - 1 : null;
  const m = be.data ? model(be.data, true) : null;
  const all = items();
  const acts = all.filter((x) => !x.info), infos = all.filter((x) => x.info);
  const row = (x) => `<button class="trow" type="button" data-a="${x.a}" ${x.v ? `data-v="${esc(x.v)}"` : ""}>
      ${x.mark || ibox(ic(x.ic), x.c)}
      <span class="row-main"><span class="row-title">${esc(x.t)}</span><span class="row-sub">${esc(x.s)}</span></span>
      <span class="chev-r">${ic("chev")}</span></button>`;
  let budgetTile;
  if (!m) budgetTile = '<span class="tile-lbl">' + ic("wallet") + "Reste à vivre</span><span class=\"tile-sub\">Chargement…</span>";
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
  fill($("homeBody"), `
    <div class="tiles">
      <button class="tile" type="button" data-a="tab" data-v="patrimoine" aria-label="Patrimoine ${n0(net)} ${base()}${p30 != null ? `, ${sgn(p30)}${pf(Math.abs(p30))} % sur 30 jours` : ""}. Ouvrir le patrimoine">
        <span class="tile-lbl">${ic("trend")}Patrimoine</span>
        <span class="tile-amt num"><span class="money">${n0(net)}</span></span>
        <span class="tile-sub">${vals.length > 1 ? `${pctOnly(p30)} sur 30 jours` : base()}</span>
        ${spark(vals)}
      </button>
      <button class="tile" type="button" data-a="tab" data-v="budget" aria-label="${budgetLabel}">${budgetTile}</button>
    </div>
    <section class="card" aria-labelledby="t-todo">
      <div class="section-head"><h2 class="section-title" id="t-todo">À traiter</h2>${acts.length ? `<span class="pill info">${acts.length}</span>` : ""}</div>
      ${acts.length ? acts.map(row).join("") : `<div class="status good">${ic("check")}<span>Rien à traiter, tout est à jour.</span></div>`}
    </section>
    ${infos.length ? `<section class="card" aria-labelledby="t-info"><h2 class="section-title" id="t-info">À savoir</h2>${infos.map(row).join("")}</section>` : ""}
    <div class="endspace"></div>`);
}

// --- propositions en attente ------------------------------------------------------------------

function by(principal) {
  if (principal.startsWith("system")) return "proposée par le hub";
  if (principal.startsWith("token:")) return "proposée par un assistant";
  return "proposée depuis l'app";
}

SHEETS.props = () => {
  const pe = store.data(pendingPath);
  const list = pe ? pe.items : [];
  if (!list.length && !busy) return null;
  const ids = list.filter((p) => !unchecked.has(p.id)).map((p) => p.id);
  return {
    title: "À valider",
    body: `<p class="hint">Rien ne change au registre sans ton Face ID. Décoche ce que tu veux garder pour plus tard.</p>` + list.map((p) => `
      <div class="prop"><input type="checkbox" id="prop-${esc(p.id)}" data-prop="${esc(p.id)}" ${unchecked.has(p.id) ? "" : "checked"}>
        <label for="prop-${esc(p.id)}"><b>${esc(p.preview.summary)}</b><span><span>${p.revision > 1 ? `révision ${p.revision} · a changé, relis-la` : by(p.created_by)}</span>${p.reason && p.created_by.startsWith("token:") ? `<span>« ${esc(p.reason)} »</span>` : ""}</span></label>
        <button class="reject" type="button" data-a="prop-reject" data-v="${esc(p.id)}">Refuser</button></div>`).join(""),
    foot: `<button class="primary" type="button" data-a="props-ok" ${ids.length && !busy ? "" : "disabled"}>${ic("faceid")}${busy ? "Validation…" : ids.length ? `Valider ${ids.length} avec Face ID` : "Rien de coché"}</button>`,
  };
};

document.addEventListener("change", (e) => {
  const id = e.target.dataset && e.target.dataset.prop;
  if (!id) return;
  if (e.target.checked) unchecked.delete(id);
  else unchecked.add(id);
  store.notify();
});

async function validate(ids) {
  busy = true;
  store.notify();
  try {
    const [text, bad] = outcome(await approve(ids));
    toast(text, { error: bad });
    if (!bad) closeSheet();
  } catch (e) {
    toast(failure(e), { error: true });
  } finally {
    busy = false;
    window.dispatchEvent(new Event("hub:changed"));
    store.invalidate();
  }
}

export const actions = {
  props: () => openSheet("props"),
  "props-ok": () => {
    const pe = store.data(pendingPath);
    const ids = (pe ? pe.items : []).filter((p) => !unchecked.has(p.id)).map((p) => p.id);
    if (ids.length) validate(ids);
  },
  "prop-reject": async (id) => {
    try {
      await api(`/proposals/${id}/reject`, {});
      toast("Proposition refusée.");
    } catch (e) {
      toast(e.message, { error: true });
    }
    store.invalidate();
  },
  gotodo: () => {
    store.set({ tx: "todo", q: "", txcat: null });
    go("journal", { top: true });
  },
  ret3a: () => {
    wealth.only("goal", "retirement");
    go("patrimoine", { top: true });
  },
};

