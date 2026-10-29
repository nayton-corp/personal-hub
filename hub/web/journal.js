// Journal : recherche, filtres (toutes, à classer, entrées, sorties, une catégorie du budget),
// écritures par jour, détail d'une écriture et classement avec Face ID ; « À classer » groupe
// par contrepartie, un choix par groupe, une validation pour tout le lot.
import { dayName, date } from "./format.js";
import { GROUP_LABEL, catIc, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { api, store } from "./store.js";
import { SHEETS, SH, amount2, announce, closeSheet, esc, failure, fill, ic, n2, openSheet, renderSheet, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);
const P = store.params;
const catsPath = "/finance/categories";
const accountsPath = "/finance/accounts";
const reviewPath = "/finance/review";
const kpisPath = () => `/finance/kpis?month=${store.today}`;
const tx = { key: null, items: [], cursor: null, loading: false, error: null };
const picks = {}; // contrepartie → catégorie choisie
const always = new Set();
let busy = false;

const internal = (e) => Boolean(e.category && e.category.id.startsWith("transfer"));
const u = (m) => m.minor / 100;

function monthEnd(month) {
  const [y, m] = month.split("-").map(Number);
  return `${month}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, "0")}`;
}

const txKey = () => `${P.tx}|${P.q}|${P.txcat ? `${P.txcat.id}:${P.txcat.from}:${P.txcat.to}` : ""}`;

async function load(more = false) {
  const key = txKey();
  if (tx.loading && !more) return;
  tx.loading = true;
  try {
    let page;
    if (P.q.length >= 3) page = await api(`/finance/search?q=${encodeURIComponent(P.q)}`);
    else {
      const qs = new URLSearchParams({ limit: "50" });
      if (P.tx === "in" || P.tx === "out") qs.set("direction", P.tx);
      if (P.txcat) {
        qs.set("category", P.txcat.id);
        qs.set("from", `${P.txcat.from}-01`);
        qs.set("to", monthEnd(P.txcat.to));
      }
      if (more && tx.cursor) qs.set("cursor", tx.cursor);
      page = await api(`/finance/entries?${qs}`);
    }
    if (key !== txKey()) return;
    let items = page.items;
    // la recherche ne filtre pas le sens : on l'applique ici
    if (P.q.length >= 3 && (P.tx === "in" || P.tx === "out")) items = items.filter((e) => (P.tx === "in" ? e.amount.minor > 0 : e.amount.minor < 0));
    tx.items = more ? tx.items.concat(items) : items;
    tx.cursor = page.next_cursor || null;
    tx.error = null;
  } catch (e) {
    tx.error = e.message;
  } finally {
    tx.loading = false;
    store.notify();
  }
}

export function reset() {
  tx.key = null;
}

export function todoCount() {
  const k = store.data(kpisPath());
  return k ? k.to_categorize : 0;
}

function catMap() {
  const c = store.data(catsPath);
  return Object.fromEntries((c ? c.items : []).map((x) => [x.id, x]));
}

export function render() {
  const cats = catMap();
  store.use(accountsPath);
  store.use(kpisPath());
  const nu = todoCount();
  const cat = P.txcat ? cats[P.txcat.id] : null;
  const span = P.txcat ? (P.txcat.from === P.txcat.to ? date(`${P.txcat.from}-01`).split(" ").slice(1).join(" ") : `${P.txcat.from} – ${P.txcat.to}`) : "";
  fill($("jChips"), (P.txcat ? `<button class="chip" type="button" data-a="jcatx" aria-label="Retirer le filtre ${esc(cat ? cat.name : P.txcat.id)}">${catIc(P.txcat.id, cat?.group)}${esc(cat ? cat.name : P.txcat.id)} · ${esc(span)}${ic("close")}</button>` : "") +
    [["all", "Toutes"], ["todo", "À classer"], ["in", "Entrées"], ["out", "Sorties"]].map(([k, l]) => `<button class="fchip" type="button" data-a="jmode" data-v="${k}" aria-pressed="${P.tx === k}">${l}${k === "todo" && nu ? `<b aria-label="${nu} en attente">${nu}</b>` : ""}</button>`).join(""));
  if (P.tx === "todo" && P.q.length < 3) return renderReview(cats);
  if (tx.key !== txKey()) {
    tx.key = txKey();
    tx.items = [];
    tx.cursor = null;
    load();
  }
  const acc = store.data(accountsPath);
  const accName = Object.fromEntries((acc ? acc.items : []).map((a) => [a.id, a.institution === a.name ? a.name : `${a.institution} · ${a.name}`]));
  const list = tx.items;
  const inn = list.filter((e) => e.amount.minor > 0 && !internal(e)).reduce((s, e) => s + u(e.amount), 0);
  const out = list.filter((e) => e.amount.minor < 0 && !internal(e)).reduce((s, e) => s - u(e.amount), 0);
  const q = P.q;
  let h = `<div class="jsum" role="status"><span><b>${list.length}</b> écriture${list.length > 1 ? "s" : ""}${tx.cursor ? " affichées" : ""}</span><span>Entrées <b class="amt-in num">+${amount2(inn)}</b></span><span>Sorties <b class="num">−${amount2(out)}</b></span>${q && q.length < 3 ? `<span>Encore ${3 - q.length} lettre${3 - q.length > 1 ? "s" : ""} pour chercher</span>` : ""}</div>`;
  if (tx.error) h += `<div class="err-box" role="alert">Impossible de charger : ${esc(tx.error)}</div>`;
  else if (!list.length) h += tx.loading ? '<div class="loading">Chargement…</div>' : `<div class="empty">Aucune écriture ne correspond.${P.txcat || q || P.tx !== "all" ? '<br><button type="button" data-a="jreset">Tout afficher</button>' : ""}</div>`;
  const today = store.data(kpisPath())?.as_of;
  const yesterday = today ? new Date(Date.parse(`${today}T00:00:00Z`) - 864e5).toISOString().slice(0, 10) : null;
  const days = [...new Set(list.map((e) => e.booking_date))];
  h += days.map((d) => {
    const es = list.filter((e) => e.booking_date === d);
    const net = es.filter((e) => !internal(e)).reduce((s, e) => s + u(e.amount), 0);
    return `<div class="day"><span>${d === today ? "Aujourd'hui · " : d === yesterday ? "Hier · " : ""}${dayName(d)}</span><span class="num">${net >= 0 ? "+" : "−"}${amount2(Math.abs(net))}</span></div>
      <div class="txlist">${es.map((e) => txRow(e, cats, accName)).join("")}</div>`;
  }).join("");
  if (tx.cursor && q.length < 3) h += `<button class="secondary more" type="button" data-a="jmore" ${tx.loading ? "disabled" : ""}>${tx.loading ? "Chargement…" : "Plus d'écritures"}</button>`;
  fill($("jBody"), h + '<div class="endspace"></div>');
}

const title = (e) => e.counterparty || e.label || (e.kind === "opening" ? "Solde d'ouverture" : "Écriture");

function txRow(e, cats, accName) {
  const c = e.category ? cats[e.category.id] : null;
  const amt = u(e.amount);
  const tag = e.category
    ? `<span class="tag">${catIc(e.category.id, c?.group)}${esc(c ? c.name : e.category.id)}</span>`
    : e.kind === "movement" ? `<span class="tag todo">${ic("help")}À classer</span>` : "";
  const ccy = e.amount.currency;
  return `<button class="row" type="button" data-a="tx" data-v="${esc(e.id)}" aria-label="${esc(title(e))}, ${amt > 0 ? "plus" : "moins"} ${n2(amt)} ${esc(ccy)}, ${e.category ? esc(c ? c.name : e.category.id) : "à classer"}">
    ${catMark(e.category ? e.category.id : null, c?.group)}
    <span class="row-main"><span class="row-title">${esc(title(e))}</span><span class="row-sub">${esc(accName[e.account_id] || "")}</span><span class="tags">${tag}</span></span>
    <span class="row-num"><span class="row-val num ${internal(e) ? "amt-int" : amt > 0 ? "amt-in" : ""}">${amt > 0 ? "+" : "−"}${amount2(Math.abs(amt))}</span>${ccy !== "CHF" ? `<span class="row-sub">${esc(ccy)}</span>` : ""}</span></button>`;
}

// --- à classer --------------------------------------------------------------------------------

function suggestions(g, cats) {
  const all = Object.values(cats).filter((c) => c.active);
  let ids;
  if (g.direction === "credit") ids = all.filter((c) => c.group === "income").map((c) => c.id);
  else {
    const b = store.data(`/finance/budget?month=${store.today}&period=m`);
    const used = b ? b.lines.filter((l) => l.category !== "a-categoriser" && cats[l.category]).map((l) => l.category) : [];
    ids = [...used, ...all.filter((c) => c.group === "variable").map((c) => c.id)];
  }
  ids = [...new Set(ids)].slice(0, 3);
  const ch = picks[g.counterparty];
  if (ch && !ids.includes(ch)) ids.push(ch);
  return ids;
}

function renderReview(cats) {
  const re = store.use(reviewPath);
  store.use(`/finance/budget?month=${store.today}&period=m`);
  if (re.status === "error") return fill($("jBody"), `<div class="err-box" role="alert">Impossible de charger : ${esc(re.error.message)}</div>`);
  if (!re.data || !Object.keys(cats).length) return fill($("jBody"), '<div class="loading">Chargement…</div>');
  const gs = re.data.groups;
  for (const cp of Object.keys(picks)) if (!gs.some((g) => g.counterparty === cp)) delete picks[cp];
  const n = Object.keys(picks).length;
  if (!gs.length) return fill($("jBody"), `<div class="empty">${ic("check")}<br>Tout est classé.<br><button type="button" data-a="jmode" data-v="all">Voir le journal</button></div>`);
  fill($("jBody"), '<p class="hint">Un choix par contrepartie. « Toujours » crée une règle qui servira aussi aux prochains imports.</p>' +
    gs.map((g, i) => {
      const tot = u(g.total), ch = picks[g.counterparty];
      return `<section class="rgroup" aria-labelledby="rg-${i}">
        <div class="ihead">${catMark(ch || null, cats[ch]?.group, "")}<span class="row-main"><span class="row-title" id="rg-${i}">${esc(g.counterparty)}</span><span class="row-sub">${g.count} écriture${g.count > 1 ? "s" : ""}</span></span><span class="row-val num ${tot > 0 ? "amt-in" : ""}">${tot > 0 ? "+" : "−"}${amount2(Math.abs(tot))}</span></div>
        <div class="sugg" role="radiogroup" aria-label="Catégorie pour ${esc(g.counterparty)}">${suggestions(g, cats).map((id) => `<button type="button" role="radio" aria-checked="${ch === id}" data-a="pick" data-v="${i}|${esc(id)}">${catIc(id, cats[id]?.group)}${esc(cats[id] ? cats[id].name : id)}</button>`).join("")}<button type="button" data-a="pickmore" data-v="${i}" aria-haspopup="dialog">Autre…</button></div>
        ${g.counterparty !== "(inconnu)" ? `<label class="check"><input type="checkbox" data-always="${i}" ${always.has(g.counterparty) ? "checked" : ""}>Toujours classer « ${esc(g.counterparty)} » ainsi</label>` : ""}
      </section>`;
    }).join("") +
    `<div class="stickyfoot"><button class="primary" type="button" data-a="review-ok" ${n && !busy ? "" : "disabled"}>${ic("faceid")}${busy ? "Validation…" : n ? `Valider ${n} choix avec Face ID` : "Choisis au moins une catégorie"}</button></div><div class="endspace"></div>`);
}

const groupAt = (i) => store.data(reviewPath)?.groups[Number(i)];

document.addEventListener("change", (e) => {
  const i = e.target.dataset && e.target.dataset.always;
  if (i == null) return;
  const g = groupAt(i);
  if (!g) return;
  if (e.target.checked) always.add(g.counterparty);
  else always.delete(g.counterparty);
});

// --- panneaux ---------------------------------------------------------------------------------

function grid(cats, direction, current, action) {
  const wanted = direction === "credit" ? ["income", "transfer"] : ["fixed", "variable", "savings", "transfer"];
  return `<div class="catgrid" role="radiogroup" aria-label="Catégorie">${wanted.map((g) => {
    const cs = Object.values(cats).filter((c) => c.active && c.group === g);
    if (!cs.length) return "";
    return `<h4>${GROUP_LABEL[g]}</h4>` + cs.map((c) => `<button type="button" role="radio" aria-checked="${current === c.id}" data-a="${action}" data-v="${esc(c.id)}">${catMark(c.id, c.group, "xs")}${esc(c.name)}</button>`).join("");
  }).join("")}</div>`;
}

SHEETS.tx = (id, sh) => {
  const de = store.use(`/finance/entries/${encodeURIComponent(id)}`);
  const cats = catMap();
  if (de.status === "error") return { title: "Écriture", body: `<div class="err-box">${esc(de.error.message)}</div>` };
  const e = de.data;
  if (!e) return { title: "Écriture", body: '<div class="loading">Chargement…</div>' };
  if (sh.tmp == null) sh.tmp = e.category ? e.category.id : "";
  const amt = u(e.amount);
  const acc = store.data(accountsPath);
  const a = acc ? acc.items.find((x) => x.id === e.account_id) : null;
  const changed = sh.tmp && sh.tmp !== (e.category ? e.category.id : "");
  const direction = amt > 0 ? "credit" : "debit";
  const raw = [e.label, e.remittance].filter(Boolean).join(" · ");
  return {
    title: esc(title(e)),
    body: `<div class="sheet-big num ${amt > 0 && !internal(e) ? "amt-in" : ""}">${amt > 0 ? "+" : "−"}${amount2(Math.abs(amt))} <small>${esc(e.amount.currency)}</small></div>
      <dl class="dl"><dt>Date</dt><dd>${dayName(e.booking_date)} ${e.booking_date.slice(0, 4)}</dd><dt>Compte</dt><dd>${esc(a ? `${a.institution} · ${a.name}` : "")}</dd>${e.counterparty_iban ? `<dt>IBAN</dt><dd class="mono">${esc(e.counterparty_iban)}</dd>` : ""}${raw ? `<dt>Libellé bancaire</dt><dd class="mono">${esc(raw)}</dd>` : ""}${e.notes && e.notes.length ? `<dt>Note</dt><dd>${esc(e.notes.map((n) => n.text).join(" · "))}</dd>` : ""}</dl>
      ${internal(e) ? `<div class="status">${ic("info")}<span>Virement entre tes comptes : exclu des revenus et des dépenses.</span></div>` : ""}
      ${e.kind === "movement" ? `<h3>Catégorie</h3>${grid(cats, direction, sh.tmp, "txcat")}
      ${e.counterparty ? `<label class="check"><input type="checkbox" id="tx-always" ${sh.always ? "checked" : ""}>Toujours classer « ${esc(e.counterparty)} » ainsi</label>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}` : ""}`,
    foot: e.kind === "movement" ? `<button class="primary" type="button" data-a="tx-ok" ${changed && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>` : "",
  };
};

SHEETS.catpick = (i) => {
  const g = groupAt(i);
  if (!g) return null;
  return {
    title: `Catégorie pour « ${esc(g.counterparty)} »`,
    body: grid(catMap(), g.direction === "credit" ? "credit" : "debit", picks[g.counterparty], "pickset"),
    foot: '<button class="secondary" type="button" data-a="sheet-close">Fermer</button>',
  };
};

document.addEventListener("change", (e) => {
  if (e.target.id === "tx-always" && SH.kind === "tx") SH.always = e.target.checked;
});

async function run(fn) {
  busy = true;
  store.notify();
  try {
    return await fn();
  } finally {
    busy = false;
    tx.key = null;
    store.notify();
  }
}

export function init() {
  fill($("search-ic"), ic("search"));
  let typing;
  $("jq").addEventListener("input", (e) => {
    clearTimeout(typing);
    typing = setTimeout(() => {
      store.set({ q: e.target.value.trim() });
      const q = e.target.value.trim();
      if (q.length >= 3) setTimeout(() => announce(`${tx.items.length} écritures`), 600);
    }, 250);
  });
}

export const actions = {
  jmode: (v) => {
    store.set({ tx: v });
    announce(v === "todo" ? "À classer" : "Journal");
  },
  jcatx: () => store.set({ txcat: null }),
  jreset: () => {
    $("jq").value = "";
    store.set({ tx: "all", q: "", txcat: null });
  },
  jmore: () => load(true),
  tx: (id) => {
    store.use(catsPath);
    openSheet("tx", id);
    SH.always = false;
  },
  txcat: (v) => { SH.tmp = v; renderSheet(); },
  "tx-ok": async () => {
    const e = store.data(`/finance/entries/${encodeURIComponent(SH.arg)}`);
    if (!e) return;
    const cat = SH.tmp;
    const items = [["recategorize", { entry_id: e.id, category_id: cat }]];
    if (SH.always && e.counterparty) items.push(["create_rule", { pattern: e.counterparty, direction: e.amount.minor > 0 ? "credit" : "debit", category_id: cat }]);
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (bad) SH.err = text;
      else {
        const name = catMap()[cat]?.name || cat;
        closeSheet();
        tx.key = null;
        toast(SH.always ? `Classée en ${name}, règle créée pour « ${e.counterparty} »` : `Classée en ${name}`);
      }
    } catch (err) {
      SH.err = failure(err);
    } finally {
      SH.busy = false;
      store.cache.delete(`/finance/entries/${encodeURIComponent(e.id)}`);
      if (SH.kind) renderSheet();
    }
  },
  pick: (v) => {
    const k = v.indexOf("|");
    const g = groupAt(v.slice(0, k));
    if (!g) return;
    const id = v.slice(k + 1);
    if (picks[g.counterparty] === id) delete picks[g.counterparty];
    else picks[g.counterparty] = id;
    store.notify();
  },
  pickmore: (i) => openSheet("catpick", i),
  pickset: (v) => {
    const g = groupAt(SH.arg);
    if (g) picks[g.counterparty] = v;
    closeSheet();
    store.notify();
  },
  "review-ok": () => run(async () => {
    const gs = (store.data(reviewPath)?.groups || []).filter((g) => picks[g.counterparty]);
    const items = [];
    for (const g of gs) {
      const cat = picks[g.counterparty];
      // la règle catégorise aussi, à l'application, les écritures en attente qui lui correspondent
      if (always.has(g.counterparty) && g.counterparty !== "(inconnu)") items.push(["create_rule", { pattern: g.counterparty, direction: g.direction, category_id: cat }]);
      else for (const id of g.entry_ids) items.push(["recategorize", { entry_id: id, category_id: cat }]);
    }
    if (!items.length) return;
    try {
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (!bad) for (const g of gs) { delete picks[g.counterparty]; always.delete(g.counterparty); }
      toast(bad ? text : `${gs.length} contrepartie${gs.length > 1 ? "s" : ""} classée${gs.length > 1 ? "s" : ""} · ${text}`, { error: bad });
    } catch (err) {
      toast(failure(err), { error: true });
    }
  }),
};
