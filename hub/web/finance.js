// Vues Finance (L2-03, L2-04) : accueil, patrimoine, budget, journal et sources, reprises du
// dashboard prototype. Aucun chiffre n'est calculé ici : chacun vient d'une route de
// /api/finance, en centimes ; l'app ne fait que la mise en forme et les graphiques.
import * as charts from "./charts.js";
import {
  chf, chf2, date, dayName, daysSince, el, initials, monthName, pct, ratio, signed, spct, units,
} from "./format.js";
import { pendingCard, pendingPath, reviewCard } from "./proposals.js";
import { api, shiftMonth, store } from "./store.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const STALE_DAYS = 45;
const ENV_LABEL = { all: "Patrimoine net", cash: "Cash", pilier3a: "3e pilier", ibkr: "IBKR", crypto: "Crypto" };
const KIND_ENV = { cash: "cash", pension: "pilier3a", securities: "ibkr", crypto: "crypto" };
const KIND_LABEL = { cash: "Cash", pension: "Prévoyance", securities: "Titres", crypto: "Crypto" };

const path = {
  kpis: () => `/finance/kpis?month=${P.month}`,
  history: () => "/finance/networth/history",
  accounts: () => "/finance/accounts",
  holdings: () => "/finance/holdings",
  freshness: () => "/finance/freshness",
  categories: () => "/finance/categories",
  budget: () => `/finance/budget?month=${P.month}&period=${P.period}`,
  totals: () => `/finance/budget/totals?month=${P.month}&period=${P.period}`,
  months: () => `/finance/budget/months?month=${P.month}&months=6`,
  flows: () => `/finance/flows?month=${P.month}`,
  collectors: () => "/collectors",
};

function pressed(id, value) {
  for (const b of $(id).querySelectorAll("button")) b.setAttribute("aria-pressed", b.dataset.v === value ? "true" : "false");
}

function text(id, value) {
  $(id).textContent = value;
}

function setBar(id, r) {
  const i = $(id);
  i.style.width = `${Math.min(100, Math.max(0, (r || 0) * 100))}%`;
  i.className = r == null ? "neutral" : r > 1 ? "over" : r > 0.85 ? "near" : "ok";
}

function setDelta(node, value, pctText, label) {
  node.className = `delta ${value >= 0 ? "up" : "down"}`;
  const [a, b, c] = node.children;
  a.textContent = signed(value);
  if (c) {
    b.textContent = pctText;
    c.textContent = label;
  } else b.textContent = label;
}

function row(ini, name, sub, val, subv, subCls, accent) {
  const r = el("div", "row");
  r.append(el("span", accent ? "av" : "av g", ini));
  const n = el("div", "n");
  n.append(el("b", "", name), el("span", "", sub));
  const v = el("div", "v");
  v.append(el("b", "amt", val));
  if (subv != null) v.append(el("span", subCls || "", subv));
  r.append(n, v);
  return r;
}

function failed(entry) {
  return entry.status === "error" ? `Impossible de charger : ${entry.error.message}` : null;
}

// --- en-tête et mois ------------------------------------------------------------------------

function header(k) {
  const sub = $("pg-sub");
  sub.classList.remove("warn");
  if (!k) return;
  if (!k.last_statement) sub.textContent = "Aucun relevé importé";
  else {
    const age = daysSince(k.last_statement);
    sub.textContent = `Relevé du ${date(k.last_statement)}`;
    if (age > STALE_DAYS) sub.classList.add("warn");
  }
}

function monthStepper(id) {
  const box = $(id);
  box.querySelector("b").textContent = monthName(P.month);
  box.querySelector('[data-step="1"]').disabled = P.month >= store.today;
}

// --- instantanés ----------------------------------------------------------------------------

function snapshotRows(key) {
  const h = store.data(path.history());
  if (!h) return null;
  return h.items.map((s) => ({
    iso: s.on_date,
    date: new Date(`${s.on_date}T00:00:00Z`),
    v: units(key === "all" ? s.net_worth : s.by_envelope[key]),
    ref: key === "all" ? units(s.deposits_cum) : null,
  }));
}

function inRange(rows, range) {
  if (range === "all") return rows;
  if (range === "ytd") {
    const year = rows[rows.length - 1].date.getUTCFullYear();
    const i = rows.findIndex((r) => r.iso === `${year - 1}-12-31`);
    return rows.slice(Math.max(0, i));
  }
  return rows.slice(-(Number(range) + 1));
}

// --- accueil --------------------------------------------------------------------------------

const RANGE_LABEL = { 1: "1 mois", 3: "3 mois", ytd: "depuis janvier", 12: "1 an", all: "depuis le début" };

function home() {
  const ke = store.use(path.kpis());
  const k = ke.data;
  const accounts = store.data(path.accounts());
  header(k);
  $("empty-home").hidden = !(accounts && accounts.items.length === 0);
  pressed("range-seg", P.range);
  pressed("mode-seg", P.mode);
  monthStepper("month-home");

  const banner = $("stale-banner");
  banner.hidden = !(k && k.stale_accounts > 0);
  if (k && k.stale_accounts > 0) {
    banner.textContent = `${k.stale_accounts} compte${k.stale_accounts > 1 ? "s" : ""} sans relevé depuis plus de ${STALE_DAYS} jours : les chiffres peuvent être en retard.`;
  }

  const hero = $("hero-val");
  const all = snapshotRows("all");
  const box = $("ch-wealth");
  if (k && all) {
    const rows = all.length ? inRange(all, P.range) : [];
    const net = units(k.net_worth);
    const first = rows[0];
    const dv = first ? net - first.v : 0;
    const dp = first && first.v ? dv / first.v : null;
    hero.textContent = P.mode === "chf" ? chf(net) : spct(dp);
    setDelta($("hero-delta"), dv, spct(dp), RANGE_LABEL[P.range]);
    $("hero-delta").hidden = rows.length < 2;
    if (P.mode === "chf") {
      charts.area(box, rows, {
        h: 190, year: P.range === "all", fmt: (v) => `${chf(v / 1000)} k`,
        tip: (r) => [`Patrimoine ${chf(r.v)} CHF`, `Versements ${chf(r.ref)} CHF`],
      });
    } else {
      charts.area(box, rows.map((r) => ({ ...r, v: first.v ? r.v / first.v - 1 : 0, ref: null })), {
        h: 190, year: P.range === "all", fmt: (v) => spct(v, 0), tip: (r) => [`Évolution ${spct(r.v)}`],
      });
    }
  } else {
    hero.textContent = "—";
    if (failed(ke)) charts.placeholder(box, failed(ke));
    else charts.clear(box);
  }

  // le mois
  const cells = ["k-income", "k-expenses", "k-savings", "k-rest"];
  if (!k) {
    for (const id of cells) text(id, "—");
    text("k-used", failed(ke) || "—");
  } else {
    text("k-income", chf(units(k.income)));
    text("k-expenses", chf(units(k.expenses)));
    text("k-savings", chf(units(k.savings)));
    const rest = units(k.rest_to_live);
    text("k-rest", rest == null ? "pas de budget" : chf(rest));
    $("k-rest").className = `amt${rest != null && rest < 0 ? " down" : ""}`;
    text("k-budget-sub", k.budget ? `budget ${chf(units(k.budget))}` : "");
    text("k-days", k.days_left ? `${k.days_left} jours restants` : "");
    const used = ratio(k.budget_used);
    text("k-used", used == null ? "Pas encore de budget : fixe des cibles par catégorie pour suivre le reste à vivre." : `${pct(used)} du budget consommé`);
    setBar("bar-budget", used);
  }

  pendingCard();

  // à traiter
  const todo = $("todo-list");
  todo.replaceChildren();
  if (!k) return;
  const items = [];
  const pending = store.data(pendingPath);
  const n = pending ? pending.items.length : 0;
  if (n > 0) items.push([`${n} proposition${n > 1 ? "s" : ""} à valider`, "un seul Face ID pour tout le lot", "accueil", String(n)]);
  if (k.stale_accounts > 0) items.push([`${k.stale_accounts} compte${k.stale_accounts > 1 ? "s" : ""} à rafraîchir`, `dernier relevé de plus de ${STALE_DAYS} jours`, "sources", "!"]);
  if (k.to_categorize > 0) items.push([`${k.to_categorize} écriture${k.to_categorize > 1 ? "s" : ""} à catégoriser`, "par contrepartie, en un Face ID", "journal", String(k.to_categorize)]);
  const p3 = k.pillar3a;
  if (p3 && p3.margin.minor > 0) items.push([`Marge 3a ${p3.year} : ${chf(units(p3.margin))} CHF`, `versé ${chf(units(p3.paid))} sur ${chf(units(p3.cap))}`, "patrimoine", "3a"]);
  if (!items.length) todo.append(el("div", "empty", "Rien à traiter."));
  for (const [title, sub, tab, ini] of items) {
    const r = row(ini, title, sub, "", null, "", tab !== "patrimoine");
    r.classList.add("go");
    r.querySelector(".v").replaceChildren(el("span", "muted", "›"));
    r.addEventListener("click", () => {
      if (tab === "accueil") $("c-props").scrollIntoView({ behavior: "smooth" });
      else store.set(tab === "journal" ? { tab, tx: "todo" } : { tab });
    });
    todo.append(r);
  }
}

// --- patrimoine -----------------------------------------------------------------------------

function patrimoine() {
  pressed("env-chips", P.env);
  const ke = store.use(path.kpis());
  const k = ke.data;
  const rows = snapshotRows(P.env);
  text("pat-lbl", ENV_LABEL[P.env]);
  if (k && rows) {
    const cur = units(P.env === "all" ? k.net_worth : k.envelopes[P.env]);
    text("pat-val", chf(cur));
    const dec = rows.find((r) => r.iso === k.change_ytd.since) || rows[0];
    setDelta($("pat-delta"), dec ? cur - dec.v : 0, "", "depuis janvier");
    charts.area($("ch-pat"), rows, { h: 160, fmt: (v) => `${chf(v / 1000)} k`, tip: (r) => [`${ENV_LABEL[P.env]} ${chf(r.v)} CHF`] });
    text("p-deposits", signed(units(k.deposits_ytd)));
    text("p-market", signed(units(k.market_ytd)));
    text("p-total", signed(units(k.change_ytd.amount)));
    $("p-market").className = `amt ${units(k.market_ytd) >= 0 ? "up" : "down"}`;
  } else if (failed(ke)) charts.placeholder($("ch-pat"), failed(ke));
  charts.hbars($("alloc"), k ? [
    { n: "Cash", v: units(k.envelopes.cash), cls: "neutral" },
    { n: "3e pilier", v: units(k.envelopes.pilier3a) },
    { n: "IBKR", v: units(k.envelopes.ibkr) },
    { n: "Crypto", v: units(k.envelopes.crypto) },
  ].sort((a, b) => b.v - a.v) : null, chf);

  positions();

  const list = $("acct-list");
  list.replaceChildren();
  const acc = store.use(path.accounts());
  if (acc.status !== "ok") {
    if (failed(acc)) list.append(el("div", "empty", failed(acc)));
    return;
  }
  const shown = acc.data.items.filter((a) => P.env === "all" || KIND_ENV[a.kind] === P.env);
  text("comptes-note", `${shown.length} compte${shown.length > 1 ? "s" : ""}`);
  if (!shown.length) list.append(el("div", "empty", "Aucun compte dans cette enveloppe."));
  for (const kind of Object.keys(KIND_LABEL)) {
    const rs = shown.filter((a) => a.kind === kind);
    if (!rs.length) continue;
    if (P.env === "all") {
      const g = el("div", "grp");
      g.append(el("span", "", KIND_LABEL[kind]), el("span", "amt", chf(rs.reduce((s, a) => s + units(a.value), 0))));
      list.append(g);
    }
    for (const a of rs) {
      const clbd = a.last_clbd && a.last_clbd.on_date;
      const age = daysSince(clbd);
      const stale = a.kind === "cash" && (age == null || age > STALE_DAYS);
      const gap = a.last_clbd && a.last_clbd.gap.minor !== 0;
      const sub = (clbd ? `relevé du ${date(clbd)}` : "aucun relevé") + (stale ? " · à rafraîchir" : "") + (gap ? " · écart au relevé" : "");
      const r = row(initials(a.institution), a.name, sub, chf(units(a.value)), a.iban || null, "", true);
      if (stale || gap) r.querySelector(".n span").className = "warn";
      list.append(r);
    }
  }
}

// positions des comptes de titres (VIAC) : valeur, plus-value latente, poids
function positions() {
  const card = $("c-positions");
  const h = store.use(path.holdings()).data;
  const show = h && h.items.length && (P.env === "all" || P.env === "pilier3a");
  card.hidden = !show;
  if (!show) return;
  const list = $("pos-list");
  list.replaceChildren();
  const gain = h.cost ? units(h.value) - units(h.cost) : null;
  text("positions-note", gain == null ? `${chf(units(h.value))} CHF` : `plus-value ${signed(gain)} CHF`);
  for (const p of h.items) {
    const sub = `${p.quantity.replace(".", ",")} parts · ${pct(ratio(p.weight), 1)}` + (p.price_date ? ` · cours du ${date(p.price_date)}` : " · sans cours");
    const g = p.gain ? units(p.gain) : null;
    list.append(row(initials(p.name), p.name, sub, chf(units(p.value)), g == null ? null : signed(g), g == null ? "" : g >= 0 ? "up" : "down", false));
  }
  const missing = $("pos-missing");
  missing.hidden = !h.missing_prices.length;
  missing.textContent = h.missing_prices.length ? `Sans cours : ${h.missing_prices.join(", ")} (valorisé au solde du registre).` : "";
}

// --- budget ---------------------------------------------------------------------------------

function budget() {
  monthStepper("month-budget");
  pressed("period-seg", P.period);
  $("period-seg").querySelector('[data-v="m"]').textContent = monthName(P.month).split(" ")[0].replace(/^./, (c) => c.toUpperCase());
  const be = store.use(path.budget());
  const b = be.data;
  const t = store.data(path.totals());
  const lines = $("flow-lines");
  lines.replaceChildren();
  if (b) {
    const rest = units(b.rest_to_live);
    const spent = units(b.expenses);
    const goal = units(b.budget);
    text("bud-lbl", P.period === "m" ? `Reste à vivre${b.days_left ? ` · ${b.days_left} jours` : ""}` : "Reste sur 3 mois de budget");
    text("bud-val", rest == null ? chf(spent) : chf(rest));
    $("bud-val").className = `hero amt${rest != null && rest < 0 ? " down" : ""}`;
    text("bud-sub", goal == null ? `${chf(spent)} dépensés · aucun budget défini` : `${chf(spent)} dépensés sur ${chf(goal)} de budget · ${pct(spent / goal)}`);
    setBar("bar-bud", goal ? spent / goal : null);
  } else {
    text("bud-val", "—");
    text("bud-sub", failed(be) || "—");
  }
  if (t) {
    for (const [n, v, cls] of [
      ["Revenus", units(t.income), ""],
      ["Dépenses fixes", -units(t.fixed), "muted"],
      ["Dépenses variables", -units(t.variable), "muted"],
      ["Épargne et investissements", units(t.savings), "up"],
    ]) {
      const kv = el("div", "kv");
      kv.append(el("span", "", n), el("b", `amt ${cls}`, signed(v)));
      lines.append(kv);
    }
    const kv = el("div", "kv total");
    kv.append(el("span", "", "Taux d'épargne"), el("b", "", pct(ratio(t.rate))));
    lines.append(kv);
  }
  const sk = $("ch-sankey");
  if (!sk.hidden) charts.sankey(sk, store.data(path.flows()));

  const list = $("cat-list");
  list.replaceChildren();
  if (b) {
    text("cat-note", b.over_count ? `${b.over_count} dépassée${b.over_count > 1 ? "s" : ""}` : "aucun dépassement");
    if (!b.lines.length) list.append(el("div", "empty", "Aucune dépense sur la période."));
    for (const [g, label] of [["fixed", "Fixe"], ["variable", "Variable"], ["mixed", "Autres"]]) {
      const gr = b.lines.filter((l) => l.group === g);
      if (!gr.length) continue;
      const head = el("div", "grp");
      const spentG = gr.reduce((s, l) => s + units(l.spent), 0);
      const goalG = gr.reduce((s, l) => s + (units(l.target) || 0), 0);
      head.append(el("span", "", label), el("span", "amt", goalG ? `${chf(spentG)} / ${chf(goalG)}` : chf(spentG)));
      list.append(head);
      for (const l of gr) {
        const hb = el("div", "hb pad");
        const top = el("div", "l");
        const v = el("span", "v", l.target ? ` / ${chf(units(l.target))}` : " hors budget");
        v.prepend(el("b", `amt${l.over ? " down" : ""}`, chf(units(l.spent))));
        top.append(el("span", "", l.name), v);
        const bar = el("div", "bar");
        const i = el("i");
        const r = ratio(l.ratio);
        i.style.width = `${Math.min(100, (r || 0) * 100)}%`;
        i.className = r == null ? "neutral" : r > 1 ? "over" : r > 0.85 ? "near" : "ok";
        bar.append(i);
        hb.append(top, bar);
        list.append(hb);
      }
    }
  }
  const m = store.data(path.months());
  charts.months($("ch-months"), m ? m.series.map((s) => ({
    month: s.month, fixed: units(s.fixed), variable: units(s.variable), savings: units(s.savings),
  })) : null);
}

// --- journal --------------------------------------------------------------------------------

const tx = { key: null, items: [], cursor: null, loading: false, error: null };

function txKey() {
  return `${P.tx}|${P.q}`;
}

async function loadTx(more = false) {
  const key = txKey();
  if (tx.loading) return;
  tx.loading = true;
  try {
    let page;
    if (P.q.length >= 3) page = await api(`/finance/search?q=${encodeURIComponent(P.q)}`);
    else {
      const qs = new URLSearchParams({ limit: "50" });
      if (P.tx === "todo") qs.set("uncategorized", "true");
      if (more && tx.cursor) qs.set("cursor", tx.cursor);
      page = await api(`/finance/entries?${qs}`);
    }
    if (key !== txKey()) return;
    tx.items = more ? tx.items.concat(page.items) : page.items;
    tx.cursor = page.next_cursor || null;
    tx.error = null;
  } catch (e) {
    tx.error = e.message;
  } finally {
    tx.loading = false;
    store.notify();
  }
}

function journal() {
  pressed("tx-chips", P.tx);
  if (tx.key !== txKey()) {
    tx.key = txKey();
    tx.items = [];
    tx.cursor = null;
    loadTx();
  }
  const k = store.data(path.kpis());
  text("todo-count", k && k.to_categorize ? String(k.to_categorize) : "");
  reviewCard(path.categories());
  const cats = store.data(path.categories());
  const names = Object.fromEntries((cats ? cats.items : []).map((c) => [c.id, c.name]));
  const acc = store.data(path.accounts());
  const accName = Object.fromEntries((acc ? acc.items : []).map((a) => [a.id, a.name]));
  const list = $("tx-list");
  list.replaceChildren();
  $("tx-more").hidden = !tx.cursor || P.q.length >= 3;
  if (tx.error) list.append(el("div", "empty", `Impossible de charger : ${tx.error}`));
  else if (!tx.items.length) list.append(el("div", "empty", tx.loading ? "Chargement…" : "Aucune écriture."));
  let lastDay = null;
  for (const e of tx.items) {
    if (e.booking_date !== lastDay) {
      lastDay = e.booking_date;
      const day = el("div", "day");
      day.append(el("span", "", dayName(e.booking_date)));
      list.append(day);
    }
    const amount = units(e.amount);
    const internal = e.category && e.category.id === "transfer-own";
    const title = e.counterparty || e.label || (e.kind === "opening" ? "Solde d'ouverture" : "Écriture");
    const r = row(initials(title), title, accName[e.account_id] || "", (amount > 0 ? "+" : "−") + chf2(Math.abs(amount)), null, "", !internal);
    const sub = r.querySelector(".n span");
    const cat = e.category ? names[e.category.id] || e.category.id : e.kind === "movement" ? "À catégoriser" : null;
    if (cat) sub.append(el("span", `chip${e.category ? "" : " todo"}`, cat));
    const v = r.querySelector(".v b");
    if (amount > 0 && !internal) v.classList.add("up");
    if (internal) v.classList.add("muted");
    list.append(r);
  }
}

// --- sources --------------------------------------------------------------------------------

const MODE_LABEL = { enabled: "actif", degraded: "suspendu", disabled: "désactivé" };
const OUTCOME_LABEL = {
  ok: "réussi", nothing_new: "rien de nouveau", auth_pending_timeout: "validation non faite",
  auth_error: "connexion refusée", site_unavailable: "site indisponible",
  selector_missing: "page changée", invalid_file: "fichier refusé", unknown: "erreur",
};
let collBusy = false;

async function collectorAction(name, call, done) {
  if (collBusy) return;
  collBusy = true;
  $("coll-msg").textContent = "";
  try {
    await call();
    $("coll-msg").textContent = done;
  } catch (e) {
    $("coll-msg").textContent = e.message;
  } finally {
    collBusy = false;
    store.cache.delete(path.collectors());
    store.notify();
  }
}

function collectorButton(label, fn) {
  const b = el("button", "link", label);
  b.type = "button";
  b.disabled = collBusy;
  b.addEventListener("click", fn);
  return b;
}

// mode, dernier passage et actions ; jamais de montant : le collecteur n'en remonte aucun
function collectorsCard() {
  const list = $("coll-list");
  list.replaceChildren();
  const c = store.use(path.collectors());
  if (c.status !== "ok") {
    list.append(el("div", "empty", failed(c) || "Chargement…"));
    return;
  }
  for (const s of c.data.items) {
    const last = s.last_run;
    const when = last ? `${OUTCOME_LABEL[last.outcome] || last.outcome} le ${date(last.started_at.slice(0, 10))}` : "jamais lancé";
    const sub = s.check_requested ? `${when} · contrôle demandé` : when;
    const r = row(initials(s.label), s.label, sub, MODE_LABEL[s.mode] || s.mode, null, "", s.mode === "enabled");
    if (s.mode !== "enabled") r.querySelector(".n span").classList.add("warn");
    r.querySelector(".v b").className = s.mode === "enabled" ? "muted" : "warn";
    const v = r.querySelector(".v");
    const post = (what, body) => api(`/collectors/${s.name}/${what}`, body);
    if (s.mode === "enabled") {
      v.append(collectorButton("Désactiver", () => collectorAction(s.name, () => post("mode", { mode: "disabled" }), `${s.label} désactivé.`)));
    } else if (s.can_enable) {
      v.append(collectorButton("Réactiver", () => collectorAction(s.name, () => post("mode", { mode: "enabled" }), `${s.label} réactivé.`)));
    } else if (!s.check_requested) {
      v.append(collectorButton("Contrôler", () => collectorAction(s.name, () => post("check", {}), "Contrôle demandé : le collecteur le lance dans la minute.")));
    }
    list.append(r);
  }
}

function sources() {
  collectorsCard();
  const list = $("fresh-list");
  list.replaceChildren();
  const f = store.use(path.freshness());
  if (f.status !== "ok") {
    list.append(el("div", "empty", failed(f) || "Chargement…"));
    return;
  }
  if (!f.data.items.length) list.append(el("div", "empty", "Aucun compte pour l'instant."));
  for (const a of f.data.items) {
    const clbd = a.last_clbd && a.last_clbd.on_date;
    const age = daysSince(clbd);
    const sub = clbd ? `relevé du ${date(clbd)} · importé le ${date(a.last_import)}` : "aucun relevé importé";
    const r = row(initials(a.name), a.name, sub, age == null ? "—" : `${age} j`, null, "", false);
    r.querySelector(".v b").className = age == null || age > STALE_DAYS ? "warn" : "muted";
    list.append(r);
  }
}

// --- assemblage -----------------------------------------------------------------------------

const VIEWS = { accueil: home, patrimoine, budget, journal, sources };
const TITLES = { accueil: "Mes finances", patrimoine: "Patrimoine", budget: "Budget", journal: "Journal", sources: "Sources" };

export function draw() {
  if ($("tabbar").hidden) return; // déconnecté : l'écran de connexion reste affiché
  for (const id of Object.keys(VIEWS)) $(id).hidden = id !== P.tab;
  for (const b of document.querySelectorAll("#tabbar button")) b.setAttribute("aria-selected", b.dataset.tab === P.tab ? "true" : "false");
  $("btn-src").setAttribute("aria-pressed", P.tab === "sources" ? "true" : "false");
  text("pg-title", TITLES[P.tab]);
  if (P.tab !== "accueil") header(store.data(path.kpis()));
  VIEWS[P.tab]();
}

function seg(id, param) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && b.dataset.v) store.set({ [param]: b.dataset.v });
  });
}

function stepper(id) {
  $(id).addEventListener("click", (e) => {
    const b = e.target.closest("button[data-step]");
    if (!b) return;
    const next = shiftMonth(P.month, Number(b.dataset.step));
    if (next <= store.today) store.set({ month: next });
  });
}

export function start() {
  if (!VIEWS[P.tab]) P.tab = "accueil";
  for (const b of document.querySelectorAll("#tabbar button")) b.addEventListener("click", () => store.set({ tab: b.dataset.tab }));
  $("btn-src").addEventListener("click", () => store.set({ tab: P.tab === "sources" ? "accueil" : "sources" }));
  $("go-budget").addEventListener("click", () => store.set({ tab: "budget" }));
  $("btn-hide").addEventListener("click", (e) => {
    const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
    e.currentTarget.setAttribute("aria-pressed", on ? "true" : "false");
    document.body.classList.toggle("hide-amounts", on);
  });
  $("btn-sankey").addEventListener("click", (e) => {
    const box = $("ch-sankey");
    box.hidden = !box.hidden;
    e.currentTarget.textContent = box.hidden ? "Voir le flux complet" : "Masquer le flux";
    store.notify();
  });
  $("tx-more").addEventListener("click", () => loadTx(true));
  let typing;
  $("tx-search").addEventListener("input", (e) => {
    clearTimeout(typing);
    typing = setTimeout(() => store.set({ q: e.target.value.trim() }), 250);
  });
  seg("range-seg", "range");
  seg("mode-seg", "mode");
  seg("env-chips", "env");
  seg("period-seg", "period");
  seg("tx-chips", "tx");
  stepper("month-home");
  stepper("month-budget");
  // au retour dans l'app (iPhone), les chiffres sont relus
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") store.invalidate();
  });
  window.addEventListener("resize", () => store.notify());
  // une validation a changé le registre : le journal se relit
  window.addEventListener("hub:changed", () => {
    tx.key = null;
  });
  store.on(draw);
  draw();
}
