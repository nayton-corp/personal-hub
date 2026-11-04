// Corriger une écriture (audit M14) : montant, date ou compte faux. Le registre ne réécrit
// rien : la carte `correct_entry` ajoute une annulation et une nouvelle écriture, liées à
// l'originale, qui reprennent sa catégorie. Tout passe par le Double Sas (Face ID).
import { date, toMinor, units } from "../../format.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";
import { SHEETS, SH, amount2, closeSheet, esc, failure, ic, openSheet, renderSheet, toast } from "../../ui.js";

const ACCOUNTS = "/finance/accounts";
const entryPath = (id) => `/finance/entries/${encodeURIComponent(id)}`;
const field = (k, label, t, attrs = "") => `<label class="field" for="corr-${k}">${label}<input id="corr-${k}" data-k="${k}" value="${esc(t[k])}" autocomplete="off" ${attrs}></label>`;
const AMOUNT = /^-?\d+(\.\d{1,2})?$/;

function initial(e) {
  return { amount: String(units(e.amount)), booking_date: e.booking_date, account_id: e.account_id, reason: "" };
}

// ce qui change par rapport à l'écriture : les paramètres de la carte, ou null si rien
export function changes(e, t) {
  const out = { entry_id: e.id, reason: (t.reason || "").trim() };
  let any = false;
  const raw = String(t.amount || "").replace(/['’\s]/g, "").replace(",", ".");
  if (!AMOUNT.test(raw)) return { error: "Montant illisible (12.50 ou -12.50)" };
  const minor = toMinor(raw);
  if (minor !== e.amount.minor) { out.amount_minor = minor; any = true; }
  if (t.booking_date && t.booking_date !== e.booking_date) { out.booking_date = t.booking_date; any = true; }
  if (t.account_id && t.account_id !== e.account_id) { out.account_id = t.account_id; any = true; }
  if (!any) return null;
  if (!out.reason) return { error: "Dis en un mot pourquoi : la raison reste dans le journal" };
  return out;
}

SHEETS.correct = (id, sh) => {
  const de = store.use(entryPath(id));
  const e = de.data;
  if (de.status === "error") return { title: "Corriger", body: `<div class="err-box">${esc(de.error.message)}</div>` };
  if (!e) return null;
  if (!sh.tmp) sh.tmp = initial(e);
  const t = sh.tmp;
  const accs = (store.use(ACCOUNTS).data || { items: [] }).items.filter((a) => a.currency === e.amount.currency && !a.closed_on);
  const accOpts = accs.map((a) => `<option value="${esc(a.id)}" ${t.account_id === a.id ? "selected" : ""}>${esc(`${a.institution} · ${a.name}`)}</option>`).join("");
  const c = changes(e, t);
  const ready = c && !c.error;
  return {
    title: "Corriger l'écriture",
    body: `<p class="hint">${esc(e.counterparty || e.label || "Écriture")} · ${date(e.booking_date)} · ${amount2(units(e.amount))} ${esc(e.amount.currency)}. Rien n'est effacé : une annulation et une nouvelle écriture s'ajoutent, liées à celle-ci, avec sa catégorie.</p>
      ${field("amount", `Montant (${esc(e.amount.currency)}, négatif pour une sortie)`, t, 'inputmode="decimal"')}
      ${field("booking_date", "Date", t, 'type="date"')}
      <label class="field" for="corr-account_id">Compte<select id="corr-account_id" data-k="account_id" class="select-full">${accOpts}</select></label>
      ${field("reason", "Pourquoi", t, 'maxlength="200" placeholder="ticket relu, mauvais compte…"')}
      ${c && c.error ? `<div class="err" role="alert">${esc(c.error)}</div>` : ""}
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="correct-save" ${ready && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Corriger avec Face ID"}</button>`,
  };
};

function keep(ev) {
  if (SH.kind !== "correct" || !SH.tmp || !ev.target.dataset || !ev.target.dataset.k) return;
  SH.tmp[ev.target.dataset.k] = ev.target.value;
  if (ev.type === "change") renderSheet();
}
document.addEventListener("input", keep);
document.addEventListener("change", keep);

export const actions = {
  "tx-correct": (id) => openSheet("correct", id),
  "correct-save": async () => {
    const e = store.data(entryPath(SH.arg));
    const c = e && SH.tmp ? changes(e, SH.tmp) : null;
    if (!c || c.error) return;
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove([["correct_entry", c]]));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast("Écriture corrigée");
      }
    } catch (err) {
      SH.err = failure(err);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};
