// Journal : recherche, sens (toutes, à classer, entrées, sorties), filtres (compte, catégorie,
// période, montant) et tri, écritures par jour, détail d'une écriture et classement avec Face ID ;
// « À classer » groupe par contrepartie avec ses libellés, comptes, dates et montants, un choix
// par groupe, une validation pour tout le lot.
import { MOIS, dayName, date } from "./format.js";
import { GROUP_LABEL, catIc, catMark } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { api, monthSpan, shiftMonth, store } from "./store.js";
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
const opened = new Set(); // groupes « À classer » dépliés
let busy = false;

const internal = (e) => Boolean(e.category && e.category.id.startsWith("transfer"));
const u = (m) => m.minor / 100;

const F = () => P.jf || {};
const searching = () => P.q.length >= 3;
const txKey = () => `${P.tx}|${searching() ? P.q : ""}|${P.txcat ? `${P.txcat.id}:${P.txcat.from}:${P.txcat.to}` : ""}|${JSON.stringify(F())}`;

function query(more) {
  const f = F();
  const qs = new URLSearchParams({ limit: "50" });
  if (P.tx === "in" || P.tx === "out") qs.set("direction", P.tx);
  if (searching()) qs.set("q", P.q);
  if (f.account) qs.set("account", f.account);
  if (f.category) qs.set("category", f.category);
  if (f.from) qs.set("from", f.from);
  if (f.to) qs.set("to", f.to);
  // le budget ouvre le journal sur une catégorie et ses mois : il prime sur les filtres
  if (P.txcat) {
    qs.set("category", P.txcat.id);
    qs.set("from", monthSpan(P.txcat.from)[0]);
    qs.set("to", monthSpan(P.txcat.to)[1]);
  }
  if (f.min != null && f.min !== "") qs.set("min_minor", String(Math.round(Number(f.min) * 100)));
  if (f.max != null && f.max !== "") qs.set("max_minor", String(Math.round(Number(f.max) * 100)));
  if (f.sort === "amount") qs.set("sort", "amount");
  if (more && tx.cursor) qs.set("cursor", tx.cursor);
  return qs;
}

async function load(more = false) {
  const key = txKey();
  if (tx.loading && !more) return;
  tx.loading = true;
  try {
    const page = await api(`/finance/entries?${query(more)}`);
    if (key !== txKey()) return;
    tx.items = more ? tx.items.concat(page.items) : page.items;
    tx.cursor = page.next_cursor || null;
    tx.error = null;
  } catch (e) {
    tx.error = e.message;
  } finally {
    tx.loading = false;
    if (key !== txKey()) tx.key = null; // les filtres ont changé pendant la requête : on relance
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

const short = (iso) => `${Number(iso.slice(8, 10))} ${MOIS[Number(iso.slice(5, 7)) - 1]}`;
const shortY = (iso) => `${short(iso)} ${iso.slice(0, 4)}`;

function accNames() {
  const acc = store.data(accountsPath);
  return Object.fromEntries((acc ? acc.items : []).map((a) => [a.id, a.institution === a.name ? a.name : `${a.institution} · ${a.name}`]));
}

// puces des filtres actifs, chacune retirable d'un toucher
function filterChips(cats) {
  const f = F(), out = [];
  const acc = accNames();
  if (f.account) out.push(["account", acc[f.account] || f.account]);
  if (f.category && !P.txcat) out.push(["category", cats[f.category]?.name || f.category]);
  if ((f.from || f.to) && !P.txcat) out.push(["period", f.from && f.to ? `${f.from.slice(0, 4) === f.to.slice(0, 4) ? short(f.from) : shortY(f.from)} – ${shortY(f.to)}` : f.from ? `dès le ${shortY(f.from)}` : `jusqu'au ${shortY(f.to)}`]);
  const hasMin = f.min != null && f.min !== "", hasMax = f.max != null && f.max !== "";
  if (hasMin || hasMax) out.push(["amount", hasMin && hasMax ? `${n2(f.min)} à ${n2(f.max)}` : hasMin ? `≥ ${n2(f.min)}` : `≤ ${n2(f.max)}`]);
  if (f.sort === "amount") out.push(["sort", "Plus gros montants"]);
  return out;
}

export function render() {
  const cats = catMap();
  store.use(accountsPath);
  store.use(kpisPath());
  const nu = todoCount();
  const cat = P.txcat ? cats[P.txcat.id] : null;
  const span = P.txcat ? (P.txcat.from === P.txcat.to ? date(`${P.txcat.from}-01`).split(" ").slice(1).join(" ") : `${P.txcat.from} – ${P.txcat.to}`) : "";
  const todo = P.tx === "todo" && !searching();
  const active = todo ? [] : filterChips(cats);
  fill($("jChips"), (todo ? "" : `<button class="fchip" type="button" data-a="jfilters" aria-haspopup="dialog" aria-pressed="${active.length > 0}">${ic("filter")}Filtres${active.length ? `<b class="cnt" aria-label="${active.length} actifs">${active.length}</b>` : ""}</button>`) +
    (P.txcat ? `<button class="chip" type="button" data-a="jcatx" aria-label="Retirer le filtre ${esc(cat ? cat.name : P.txcat.id)}">${catIc(P.txcat.id, cat?.group)}${esc(cat ? cat.name : P.txcat.id)} · ${esc(span)}${ic("close")}</button>` : "") +
    active.map(([k, l]) => `<button class="chip" type="button" data-a="jfx" data-v="${k}" aria-label="Retirer le filtre ${esc(l)}">${esc(l)}${ic("close")}</button>`).join("") +
    [["all", "Toutes"], ["todo", "À classer"], ["in", "Entrées"], ["out", "Sorties"]].map(([k, l]) => `<button class="fchip" type="button" data-a="jmode" data-v="${k}" aria-pressed="${P.tx === k}">${l}${k === "todo" && nu ? `<b aria-label="${nu} en attente">${nu}</b>` : ""}</button>`).join(""));
  if (todo) return renderReview(cats);
  if (tx.key !== txKey()) {
    tx.key = txKey();
    tx.items = [];
    tx.cursor = null;
    load();
  }
  const accName = accNames();
  const list = tx.items;
  const inn = list.filter((e) => e.amount.minor > 0 && !internal(e)).reduce((s, e) => s + u(e.amount), 0);
  const out = list.filter((e) => e.amount.minor < 0 && !internal(e)).reduce((s, e) => s - u(e.amount), 0);
  const q = P.q;
  const filtered = P.txcat || q || P.tx !== "all" || active.length;
  let h = `<div class="jsum" role="status"><span><b>${list.length}</b> écriture${list.length > 1 ? "s" : ""}${tx.cursor ? " affichées" : ""}</span><span>Entrées <b class="amt-in num">+${amount2(inn)}</b></span><span>Sorties <b class="num">−${amount2(out)}</b></span>${q && q.length < 3 ? `<span>Encore ${3 - q.length} lettre${3 - q.length > 1 ? "s" : ""} pour chercher</span>` : ""}</div>`;
  if (tx.error) h += `<div class="err-box" role="alert">Impossible de charger : ${esc(tx.error)}</div>`;
  else if (!list.length) h += tx.loading ? '<div class="loading">Chargement…</div>' : `<div class="empty">Aucune écriture ne correspond.${filtered ? '<br><button type="button" data-a="jreset">Tout afficher</button>' : ""}</div>`;
  if (F().sort === "amount") {
    // trié par montant : une seule liste, la date passe sous le nom
    if (list.length) h += `<div class="txlist">${list.map((e) => txRow(e, cats, accName, true)).join("")}</div>`;
  } else {
    const today = store.data(kpisPath())?.as_of;
    const yesterday = today ? new Date(Date.parse(`${today}T00:00:00Z`) - 864e5).toISOString().slice(0, 10) : null;
    const days = [...new Set(list.map((e) => e.booking_date))];
    h += days.map((d) => {
      const es = list.filter((e) => e.booking_date === d);
      const net = es.filter((e) => !internal(e)).reduce((s, e) => s + u(e.amount), 0);
      return `<div class="day"><span>${d === today ? "Aujourd'hui · " : d === yesterday ? "Hier · " : ""}${dayName(d)}</span><span class="num">${net >= 0 ? "+" : "−"}${amount2(Math.abs(net))}</span></div>
      <div class="txlist">${es.map((e) => txRow(e, cats, accName)).join("")}</div>`;
    }).join("");
  }
  if (tx.cursor) h += `<button class="secondary more" type="button" data-a="jmore" ${tx.loading ? "disabled" : ""}>${tx.loading ? "Chargement…" : "Plus d'écritures"}</button>`;
  fill($("jBody"), h + '<div class="endspace"></div>');
}

const title = (e) => e.counterparty || e.label || (e.kind === "opening" ? "Solde d'ouverture" : "Écriture");

function txRow(e, cats, accName, dated = false) {
  const c = e.category ? cats[e.category.id] : null;
  const amt = u(e.amount);
  const tag = e.category
    ? `<span class="tag">${catIc(e.category.id, c?.group)}${esc(c ? c.name : e.category.id)}</span>`
    : e.kind === "movement" ? `<span class="tag todo">${ic("help")}À classer</span>` : "";
  const ccy = e.amount.currency;
  return `<button class="row" type="button" data-a="tx" data-v="${esc(e.id)}" aria-label="${esc(title(e))}, ${amt > 0 ? "plus" : "moins"} ${n2(amt)} ${esc(ccy)}, ${e.category ? esc(c ? c.name : e.category.id) : "à classer"}">
    ${catMark(e.category ? e.category.id : null, c?.group)}
    <span class="row-main"><span class="row-title">${esc(title(e))}</span><span class="row-sub">${dated ? `${esc(shortY(e.booking_date))} · ` : ""}${esc(accName[e.account_id] || "")}</span><span class="tags">${tag}</span></span>
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
  const accName = accNames();
  fill($("jBody"), '<p class="hint">Un choix par contrepartie. « Toujours » crée une règle qui servira aussi aux prochains imports.</p>' +
    gs.map((g, i) => {
      const tot = u(g.total), ch = picks[g.counterparty], open = opened.has(g.counterparty);
      const when = g.first_date === g.last_date ? shortY(g.last_date) : `${g.first_date.slice(0, 4) === g.last_date.slice(0, 4) ? short(g.first_date) : shortY(g.first_date)} – ${shortY(g.last_date)}`;
      const lo = Math.abs(u(g.min)), hi = Math.abs(u(g.max));
      const range = g.count < 2 ? "" : lo === hi ? `${n2(hi)} chaque fois` : `de ${n2(lo)} à ${n2(hi)}`;
      const raw = [...g.labels.filter((l) => normal(l) !== g.counterparty), ...g.remittances];
      const accs = g.accounts.map((a) => accName[a] || a).join(", ");
      return `<section class="rgroup" aria-labelledby="rg-${i}">
        <div class="ihead">${catMark(ch || null, cats[ch]?.group, "")}<span class="row-main"><span class="row-title" id="rg-${i}">${esc(g.counterparty)}</span><span class="row-sub">${g.count} écriture${g.count > 1 ? "s" : ""} · ${esc(when)}</span></span><span class="row-val num ${tot > 0 ? "amt-in" : ""}">${tot > 0 ? "+" : "−"}${amount2(Math.abs(tot))}</span></div>
        <dl class="rfacts"><dt>Compte</dt><dd>${esc(accs)}</dd>${range ? `<dt>Montants</dt><dd class="num">${esc(range)}</dd>` : ""}${raw.length ? `<dt>Libellé</dt><dd class="mono">${raw.slice(0, 3).map(esc).join("<br>")}</dd>` : ""}</dl>
        <button class="link rtoggle" type="button" data-a="rgopen" data-v="${i}" aria-expanded="${open}" aria-controls="rg-tx-${i}">${ic("chev")}${open ? "Masquer" : g.count > 1 ? `Voir ${g.count > g.samples.length ? `les ${g.samples.length} dernières` : `les ${g.count}`} écritures` : "Voir l'écriture"}</button>
        ${open ? `<div class="txlist rtx" id="rg-tx-${i}">${g.samples.map((x) => sampleRow(x, accName)).join("")}</div>` : ""}
        <div class="sugg" role="radiogroup" aria-label="Catégorie pour ${esc(g.counterparty)}">${suggestions(g, cats).map((id) => `<button type="button" role="radio" aria-checked="${ch === id}" data-a="pick" data-v="${i}|${esc(id)}">${catIc(id, cats[id]?.group)}${esc(cats[id] ? cats[id].name : id)}</button>`).join("")}<button type="button" data-a="pickmore" data-v="${i}" aria-haspopup="dialog">Autre…</button></div>
        ${g.counterparty !== "(inconnu)" ? `<label class="check"><input type="checkbox" data-always="${i}" ${always.has(g.counterparty) ? "checked" : ""}>Toujours classer « ${esc(g.counterparty)} » ainsi</label>` : ""}
      </section>`;
    }).join("") +
    `<div class="stickyfoot"><button class="primary" type="button" data-a="review-ok" ${n && !busy ? "" : "disabled"}>${ic("faceid")}${busy ? "Validation…" : n ? `Valider ${n} choix avec Face ID` : "Choisis au moins une catégorie"}</button></div><div class="endspace"></div>`);
}

// même normalisation que le serveur pour le groupe : un libellé égal au nom n'apprend rien
const normal = (s) => String(s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

function sampleRow(x, accName) {
  const amt = u(x.amount);
  const raw = [x.label, x.remittance].filter(Boolean).join(" · ");
  return `<button class="row" type="button" data-a="tx" data-v="${esc(x.id)}" aria-label="${esc(shortY(x.booking_date))}, ${amt > 0 ? "plus" : "moins"} ${n2(amt)} ${esc(x.amount.currency)}">
    <span class="row-main"><span class="row-title">${esc(dayName(x.booking_date))} ${x.booking_date.slice(0, 4)}</span><span class="row-sub">${esc(accName[x.account_id] || "")}</span>${raw ? `<span class="row-sub mono">${esc(raw)}</span>` : ""}</span>
    <span class="row-num"><span class="row-val num ${amt > 0 ? "amt-in" : ""}">${amt > 0 ? "+" : "−"}${amount2(Math.abs(amt))}</span></span></button>`;
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

// filtres : le panneau travaille sur une copie, appliquée d'un coup par « Afficher »
const PERIODS = [["m0", "Ce mois"], ["m1", "Mois dernier"], ["m3", "3 derniers mois"], ["y", "Cette année"]];

function periodOf(k) {
  const m = store.today;
  if (k === "m0") return monthSpan(m);
  if (k === "m1") return monthSpan(shiftMonth(m, -1));
  if (k === "m3") return [monthSpan(shiftMonth(m, -2))[0], monthSpan(m)[1]];
  return [`${m.slice(0, 4)}-01-01`, `${m.slice(0, 4)}-12-31`];
}

SHEETS.jfilter = (_arg, sh) => {
  if (!sh.tmp) sh.tmp = { ...F() };
  const t = sh.tmp, cats = catMap();
  const acc = store.data(accountsPath);
  const accs = (acc ? acc.items : []).slice().sort((a, b) => (a.institution || "").localeCompare(b.institution || "", "fr") || a.name.localeCompare(b.name, "fr"));
  const opt = (v, l, cur) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(l)}</option>`;
  const catOpts = Object.keys(GROUP_LABEL).map((g) => {
    const cs = Object.values(cats).filter((c) => c.group === g && (c.active || c.id === t.category));
    return cs.length ? `<optgroup label="${esc(GROUP_LABEL[g])}">${cs.map((c) => opt(c.id, c.name, t.category)).join("")}</optgroup>` : "";
  }).join("");
  const per = PERIODS.find(([k]) => { const [a, b] = periodOf(k); return t.from === a && t.to === b; });
  return {
    title: "Filtrer le journal",
    body: `<div class="form">
      <label for="jf-account">Compte</label><select id="jf-account" data-jf="account">${opt("", "Tous les comptes", t.account || "")}${accs.map((a) => opt(a.id, a.institution === a.name ? a.name : `${a.institution} · ${a.name}`, t.account)).join("")}</select>
      <label for="jf-category">Catégorie</label><select id="jf-category" data-jf="category">${opt("", "Toutes les catégories", t.category || "")}${catOpts}</select>
      ${P.txcat ? '<p class="hint">Le budget a ouvert le journal sur une catégorie : elle prime tant que sa puce est affichée.</p>' : ""}
      <label id="jf-per-l">Période</label>
      <div class="seg small jf-per" role="group" aria-labelledby="jf-per-l">${PERIODS.map(([k, l]) => `<button type="button" data-a="jfper" data-v="${k}" aria-pressed="${per?.[0] === k}">${l}</button>`).join("")}</div>
      <div class="jf-pair"><label>Du<input type="date" data-jf="from" value="${esc(t.from || "")}"></label><label>Au<input type="date" data-jf="to" value="${esc(t.to || "")}"></label></div>
      <label id="jf-amt-l">Montant</label>
      <div class="jf-pair" role="group" aria-labelledby="jf-amt-l"><label>Au moins<input type="number" inputmode="decimal" min="0" step="0.01" placeholder="0" data-jf="min" value="${esc(t.min ?? "")}"></label><label>Au plus<input type="number" inputmode="decimal" min="0" step="0.01" placeholder="sans limite" data-jf="max" value="${esc(t.max ?? "")}"></label></div>
      <p class="hint">En valeur absolue, entrées comme sorties.</p>
      <label id="jf-sort-l">Trier par</label>
      <div class="seg" role="group" aria-labelledby="jf-sort-l">${[["date", "Date"], ["amount", "Montant"]].map(([k, l]) => `<button type="button" data-a="jfsort" data-v="${k}" aria-pressed="${(t.sort || "date") === k}">${l}</button>`).join("")}</div>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}</div>`,
    foot: '<div class="foot2"><button class="secondary" type="button" data-a="jfclear">Effacer</button><button class="primary" type="button" data-a="jfapply">Afficher</button></div>',
  };
};

const jfInput = (e) => {
  const k = e.target.dataset && e.target.dataset.jf;
  if (!k || SH.kind !== "jfilter" || !SH.tmp) return;
  SH.tmp[k] = e.target.value;
  if (e.type === "change" && (k === "from" || k === "to")) renderSheet(); // l'intervalle rapide suit
};
document.addEventListener("input", jfInput);
document.addEventListener("change", jfInput);

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
    store.set({ tx: "all", q: "", txcat: null, jf: {} });
  },
  jfilters: () => {
    store.use(catsPath);
    openSheet("jfilter", null);
  },
  jfper: (k) => {
    [SH.tmp.from, SH.tmp.to] = periodOf(k);
    renderSheet();
  },
  jfsort: (k) => { SH.tmp.sort = k; renderSheet(); },
  jfclear: () => { SH.tmp = {}; SH.err = ""; renderSheet(); },
  jfapply: () => {
    const t = Object.fromEntries(Object.entries(SH.tmp).filter(([, v]) => v !== "" && v != null && !(typeof v === "number" && Number.isNaN(v))));
    if (t.sort === "date") delete t.sort;
    if (t.from && t.to && t.from > t.to) { SH.err = "La date de début suit la date de fin."; return renderSheet(); }
    if (t.min != null && t.max != null && Number(t.min) > Number(t.max)) { SH.err = "Le montant minimum dépasse le maximum."; return renderSheet(); }
    closeSheet();
    store.set({ jf: t, ...(t.category || t.from || t.to ? { txcat: null } : {}) });
  },
  jfx: (k) => {
    const t = { ...F() };
    if (k === "period") { delete t.from; delete t.to; }
    else if (k === "amount") { delete t.min; delete t.max; }
    else delete t[k];
    store.set({ jf: t });
  },
  rgopen: (i) => {
    const g = groupAt(i);
    if (!g) return;
    if (opened.has(g.counterparty)) opened.delete(g.counterparty);
    else opened.add(g.counterparty);
    store.notify();
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
