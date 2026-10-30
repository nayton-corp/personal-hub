// Dettes : crédit, hypothèque, leasing, prêt étudiant… Une dette part d'un solde à une date, ou
// du versement reçu du prêteur (choisi dans le journal) ; son solde baisse de chaque paiement de
// sa catégorie (depuis son compte s'il est choisi), et un relevé du prêteur le corrige. La
// mensualité et l'échéance sont facultatives : sans mensualité, la fin projetée suit les
// derniers paiements. Tout s'enregistre avec un seul Face ID.
import { date } from "../../format.js";
import { GROUP_LABEL } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";
import { SHEETS, SH, amount2, closeSheet, esc, failure, fill, ibox, ic, openSheet, renderSheet, toast } from "../../ui.js";

const $ = (id) => document.getElementById(id);
export const DEBTS = "/finance/debts";
const ACCOUNTS = "/finance/accounts", CATS = "/finance/categories";
export const DEBT_KIND = { loan: "Crédit", mortgage: "Hypothèque", leasing: "Leasing", student: "Prêt étudiant", credit: "Carte de crédit", other: "Autre dette" };
const KIND_IC = { loan: "car", mortgage: "home", leasing: "car", student: "briefcase", credit: "wallet", other: "landmark" };
export const debtMark = (d, size = "") => ibox(ic(KIND_IC[d.kind] || "landmark"), "var(--neg)", size);

const today = () => new Date().toISOString().slice(0, 10);
const u = (m) => (m == null ? null : m.minor / 100);
const txt = (m) => (m == null ? "" : String(m.minor / 100));
// « 12'500,50 » → centimes ; "" → null ; illisible → NaN
function minor(s) {
  const t = String(s ?? "").replace(/['’\s]/g, "").replace(",", ".");
  if (!t) return null;
  return /^\d+(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 100) : NaN;
}
const find = (id) => ((store.data(DEBTS) || {}).items || []).find((d) => d.id === id) || null;

function initial(d, seed) {
  if (!d) return { name: "", lender: "", kind: "loan", mode: "date", balance: "", balance_on: today(), original: "", rate: "", payment: "", ends_on: "", category_id: "", account_id: "", ...seed };
  return { name: d.name, lender: d.lender, kind: d.kind, original: txt(d.original), rate: d.rate_pct || "", payment: txt(d.payment), ends_on: d.ends_on || "", category_id: d.category_id || "", account_id: d.account_id || "", stmt: "", stmt_on: today() };
}

// paramètres de save_debt : tout pour une création, les seuls champs changés sinon
function params(d, t) {
  const out = {};
  const put = (k, v, was) => { if (!d || v !== was) out[k] = v; };
  for (const k of ["name", "lender"]) put(k, t[k].trim(), d && d[k]);
  put("kind", t.kind, d && d.kind);
  const amounts = [["original_minor", t.original, d && d.original], ["payment_minor", t.payment, d && d.payment]];
  for (const [k, s, was] of amounts) {
    const v = minor(s);
    if (Number.isNaN(v)) throw new Error("Montant illisible");
    if (d ? (v || 0) !== (was ? was.minor : 0) : v) out[k] = v || 0;
  }
  const rate = String(t.rate || "").replace(",", ".").trim();
  if (rate && !/^\d{1,2}(\.\d{1,4})?$/.test(rate)) throw new Error("Taux illisible (en %, par exemple 2,5)");
  if (d ? (rate || "0") !== (d.rate_pct || "0") : rate) out.rate_pct = rate || "0";
  put("ends_on", t.ends_on || "", d && (d.ends_on || ""));
  put("category_id", t.category_id || "", d && (d.category_id || ""));
  put("account_id", t.account_id || "", d && (d.account_id || ""));
  if (!d) {
    if (!out.name || !out.lender) throw new Error("Nom et prêteur requis");
    if (t.mode === "entry") out.opening_entry_id = t.entry;
    else {
      const b = minor(t.balance);
      if (!b) throw new Error("Solde de départ requis");
      Object.assign(out, { balance_minor: b, balance_on: t.balance_on });
    }
    for (const k of ["ends_on", "category_id", "account_id"]) if (!out[k]) delete out[k];
  }
  return out;
}

const radio = (key, list, cur) => `<div class="catgrid" role="radiogroup">${list.map(([v, label, mark]) => `<button type="button" role="radio" aria-checked="${cur === v}" data-a="debt-pick" data-v="${key}|${v}">${mark || ""}${esc(label)}</button>`).join("")}</div>`;
const input = (k, label, t, attrs = "") => `<label class="field" for="debt-${k}">${label}<input id="debt-${k}" data-k="${k}" value="${esc(t[k])}" autocomplete="off" ${attrs}></label>`;
const money = (k, label, t) => input(k, label, t, 'inputmode="decimal" placeholder="0.00"');
const day = (k, label, t) => input(k, label, t, 'type="date"');

SHEETS.debt = (id, sh) => {
  const d = id ? find(id) : null;
  if (id && !d) return null;
  if (!sh.tmp || !("name" in sh.tmp)) sh.tmp = initial(d, sh.tmp || {});
  const t = sh.tmp;
  const cats = (store.use(CATS).data || { items: [] }).items;
  const accs = (store.use(ACCOUNTS).data || { items: [] }).items;
  const catOpts = ["fixed", "variable", "savings"].map((g) => {
    const cs = cats.filter((c) => c.group === g && (c.active || c.id === t.category_id));
    return cs.length ? `<optgroup label="${esc(GROUP_LABEL[g])}">${cs.map((c) => `<option value="${esc(c.id)}" ${t.category_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</optgroup>` : "";
  }).join("");
  const accOpts = accs.filter((a) => a.kind === "cash").map((a) => `<option value="${esc(a.id)}" ${t.account_id === a.id ? "selected" : ""}>${esc(`${a.institution} · ${a.name}`)}</option>`).join("");
  const start = d
    ? `<dl class="dl"><dt>Solde aujourd'hui</dt><dd>${amount2(u(d.balance))} ${esc(d.currency)}</dd><dt>Dernier solde connu</dt><dd>${d.stated ? `${amount2(u(d.stated))} au ${date(d.stated_on)}` : "—"}</dd></dl>
      <h3 class="field">Relevé du prêteur</h3>
      <p class="hint">Un solde lu sur un relevé remplace le calcul à partir de sa date.</p>
      <div class="two">${money("stmt", "Solde constaté", t)}${day("stmt_on", "Au", t)}</div>`
    : `<h3 class="field">Départ</h3>
      ${radio("mode", [["date", "Solde à une date"], ["entry", "Versement reçu"]], t.mode)}
      ${t.mode === "entry"
        ? (t.entry ? `<p class="hint">Versement du ${date(t.entry_on)} : <b>${amount2(t.entry_amount)}</b>. La dette part de ce montant à cette date.</p>` : '<p class="hint">Ouvre le versement reçu du prêteur dans le Journal, puis « Créer une dette depuis ce versement ».</p>')
        : `<div class="two">${money("balance", "Solde restant", t)}${day("balance_on", "Au", t)}</div><p class="hint">Le montant emprunté à la date du prêt, ou ce qu'il reste à rembourser aujourd'hui.</p>`}`;
  return {
    title: d ? `${debtMark(d)}<span>${esc(d.name)}</span>` : "Nouvelle dette",
    body: `
      ${input("name", "Nom", t, 'maxlength="60" placeholder="Crédit voiture"')}
      ${input("lender", "Prêteur", t, 'maxlength="60" placeholder="Banque, leasing, particulier"')}
      <h3 class="field">Type</h3>
      ${radio("kind", Object.entries(DEBT_KIND).map(([k, l]) => [k, l, ibox(ic(KIND_IC[k]), "var(--neg)", "xs")]), t.kind)}
      ${start}
      <h3 class="field">Remboursements</h3>
      <label class="field" for="debt-cat">Catégorie des paiements<select id="debt-cat" data-k="category_id" class="select-full"><option value="" ${t.category_id ? "" : "selected"}>Aucune (solde saisi à la main)</option>${catOpts}</select></label>
      <label class="field" for="debt-acc">Depuis le compte<select id="debt-acc" data-k="account_id" class="select-full"><option value="" ${t.account_id ? "" : "selected"}>Tous les comptes</option>${accOpts}</select></label>
      <p class="hint">Chaque paiement de cette catégorie fait baisser le solde, quel que soit son montant : une mensualité qui change suit d'elle-même.</p>
      <div class="two">${money("payment", "Mensualité actuelle (facultatif)", t)}${input("rate", "Taux annuel en %", t, 'inputmode="decimal" placeholder="0"')}</div>
      <div class="two">${money("original", "Montant emprunté (facultatif)", t)}${day("ends_on", "Échéance (facultatif)", t)}</div>
      ${d ? `<div class="setrow"><span id="debt-close-lbl">${d.closed_on ? `Soldée le ${date(d.closed_on)}` : "Dette soldée"}<small>${d.closed_on ? "Elle ne compte plus dans le patrimoine." : "La sortir du patrimoine à partir d'aujourd'hui."}</small></span><button class="secondary" type="button" data-a="debt-close" ${sh.busy ? "disabled" : ""}>${d.closed_on ? "Rouvrir" : "Marquer soldée"}</button></div>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="debt-save" ${sh.busy || (!d && t.mode === "entry" && !t.entry) ? "disabled" : ""}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

function keep(e) {
  if (SH.kind !== "debt" || !SH.tmp || !e.target.dataset || !e.target.dataset.k) return;
  SH.tmp[e.target.dataset.k] = e.target.value;
}
document.addEventListener("input", keep);
document.addEventListener("change", keep);

async function run(items, done) {
  SH.busy = true;
  SH.err = "";
  renderSheet();
  try {
    const [text, bad] = outcome(await proposeAndApprove(items));
    if (bad) SH.err = text;
    else {
      closeSheet();
      toast(done);
    }
  } catch (e) {
    SH.err = failure(e);
  } finally {
    SH.busy = false;
    if (SH.kind) renderSheet();
  }
}

// --- carte « Dettes » des réglages -------------------------------------------------------------

export function debtsList() {
  const de = store.use(DEBTS);
  if (de.status === "error") return fill($("debt-list"), `<div class="empty">Impossible de charger : ${esc(de.error.message)}</div>`);
  if (!de.data) return fill($("debt-list"), '<div class="empty">Chargement…</div>');
  if (!de.data.items.length) return fill($("debt-list"), '<div class="empty">Aucune dette. Ajoute un crédit, une hypothèque ou un leasing pour que le patrimoine soit net.</div>');
  fill($("debt-list"), de.data.items.map((d) => {
    const sub = d.closed_on ? `soldée le ${date(d.closed_on)}` : `${DEBT_KIND[d.kind]} · ${d.lender}${d.projected_end ? ` · fin vers ${d.projected_end.slice(5)}.${d.projected_end.slice(0, 4)}` : ""}`;
    return `<button class="row" type="button" data-a="debt-edit" data-v="${esc(d.id)}" aria-label="${esc(d.name)}, ${esc(sub)}. Modifier">
      ${debtMark(d)}
      <span class="row-main"><span class="row-title">${esc(d.name)}</span><span class="row-sub">${esc(sub)}</span></span>
      <span class="row-num"><span class="row-val num">−${amount2(u(d.balance))}</span></span></button>`;
  }).join(""));
}

// détail d'une dette dans le patrimoine
export function debtDetail(id) {
  const d = find(id);
  if (!d) return "";
  const orig = u(d.original), bal = u(d.balance);
  const done = orig ? Math.max(0, Math.min(1, 1 - bal / orig)) : null;
  return `<div class="sub-head"><span>${esc(DEBT_KIND[d.kind])} · ${esc(d.lender)}</span><button class="linkish" type="button" data-a="debt-edit" data-v="${esc(d.id)}">Modifier</button></div>
    ${done != null ? `<div class="sharebar"><i data-css="width:${(done * 100).toFixed(1)}%"></i></div><p class="hint">${Math.round(done * 100)} % remboursé sur ${amount2(orig)} ${esc(d.currency)}</p>` : ""}
    <dl class="dl">
      <dt>Solde</dt><dd>${amount2(bal)} ${esc(d.currency)}</dd>
      ${d.stated_on ? `<dt>Depuis le ${date(d.stated_on)}</dt><dd>${d.payments_since} paiement${d.payments_since > 1 ? "s" : ""} · ${amount2(u(d.paid_since))}</dd>` : ""}
      ${d.interest_since && d.interest_since.minor ? `<dt>Intérêts courus</dt><dd>${amount2(u(d.interest_since))}</dd>` : ""}
      ${d.usual_payment ? `<dt>${d.payment ? "Mensualité" : "Paiement habituel"}</dt><dd>${amount2(u(d.usual_payment))}</dd>` : ""}
      ${d.last_payment ? `<dt>Dernier paiement</dt><dd>${date(d.last_payment)}</dd>` : ""}
      ${d.projected_end ? `<dt>Fin projetée</dt><dd>${d.projected_end.slice(5)}.${d.projected_end.slice(0, 4)}</dd>` : ""}
      ${d.ends_on ? `<dt>Échéance</dt><dd>${date(d.ends_on)}</dd>` : ""}
      <dt>Paiements</dt><dd>${d.category_name ? `${esc(d.category_name)}${d.account_name ? ` depuis ${esc(d.account_name)}` : ""}` : "saisis à la main"}</dd>
    </dl>`;
}

export const actions = {
  "debt-add": () => openSheet("debt", null),
  "debt-edit": (id) => openSheet("debt", id),
  // depuis le journal : le versement reçu du prêteur
  "debt-from": (v) => {
    const [id, on, amt, who] = v.split("|");
    openSheet("debt", null, { mode: "entry", entry: id, entry_on: on, entry_amount: Number(amt), lender: who || "", balance: "", balance_on: on });
  },
  "debt-pick": (v) => {
    if (!SH.tmp) return;
    const i = v.indexOf("|");
    SH.tmp[v.slice(0, i)] = v.slice(i + 1);
    renderSheet();
  },
  "debt-save": async () => {
    const d = SH.arg ? find(SH.arg) : null;
    const items = [];
    try {
      const p = params(d, SH.tmp);
      if (d) {
        if (Object.keys(p).length) items.push(["save_debt", { debt_id: d.id, ...p }]);
        const s = minor(SH.tmp.stmt);
        if (Number.isNaN(s)) throw new Error("Solde constaté illisible");
        if (s != null) items.push(["record_debt_balance", { debt_id: d.id, on_date: SH.tmp.stmt_on, amount_minor: s }]);
        if (!items.length) throw new Error("Aucun changement");
      } else items.push(["save_debt", p]);
    } catch (e) {
      SH.err = e.message;
      return renderSheet();
    }
    await run(items, d ? "Dette enregistrée" : "Dette ajoutée au patrimoine");
  },
  "debt-close": async () => {
    const d = find(SH.arg);
    if (!d) return;
    await run([["save_debt", { debt_id: d.id, closed_on: d.closed_on ? "" : today() }]], d.closed_on ? "Dette rouverte" : "Dette soldée");
  },
};
