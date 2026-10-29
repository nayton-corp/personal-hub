// Réglages d'un compte : nom, objectif, disponibilité, catégorie, masquage et catégorie de toutes
// ses dépenses (une poche Vacances), enregistrés par un seul Face ID. Le panneau s'ouvre depuis le patrimoine (détail d'un
// compte) ou depuis la carte « Comptes » des réglages, qui montre aussi la fraîcheur.
import { date, daysSince } from "./format.js";
import { FACET, GROUP_LABEL, facetMark, facetName, setInstitutions } from "./meta.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "./store.js";
import { SHEETS, SH, closeSheet, esc, failure, fill, ibox, ic, openSheet, renderSheet, toast } from "./ui.js";

const $ = (id) => document.getElementById(id);
const ACCOUNTS = "/finance/accounts", FRESH = "/finance/freshness", CATS = "/finance/categories";
const SPEND_PRIORITY = 5; // avant les règles par mot : tout débit du compte va dans la catégorie
export const STALE_DAYS = 45;
const KIND = { cash: "Compte", securities: "Titres", pension: "Prévoyance", crypto: "Crypto" };

const find = (id) => {
  const acc = store.data(ACCOUNTS);
  return acc ? acc.items.find((a) => a.id === id) : null;
};
export const hiddenIds = () => new Set(((store.data(ACCOUNTS) || {}).items || []).filter((a) => a.hidden).map((a) => a.id));

// état saisi : ce que le compte vaut aujourd'hui, modifié par les choix du panneau
function initial(a) {
  return { name: a.name, goal: a.goal, availability: a.availability_set ? a.availability : "auto", category: a.category || "auto", hidden: a.hidden, spend: a.spend_rule ? a.spend_rule.category_id : "" };
}
function changes(a, t) {
  const now = initial(a), out = {};
  for (const k of Object.keys(now)) if (t[k] !== now[k]) out[k] = t[k];
  return "name" in out && !out.name.trim() ? null : out;
}

const radio = (key, list, cur) => `<div class="catgrid" role="radiogroup" aria-label="${esc(FACET[key === "availability" ? "liq" : key === "category" ? "cat" : key].label)}">${list.map(([v, label, mark]) =>
  `<button type="button" role="radio" aria-checked="${cur === v}" data-a="acc-pick" data-v="${key}|${v}">${mark}${esc(label)}</button>`).join("")}</div>`;

SHEETS.account = (id, sh) => {
  const a = find(id);
  if (!a) return null;
  if (!sh.tmp) sh.tmp = initial(a);
  const t = sh.tmp, diff = changes(a, t);
  const cats = (store.use(CATS).data || { items: [] }).items;
  const spendOpts = ["fixed", "variable"].map((g) => {
    const cs = cats.filter((c) => c.group === g && (c.active || c.id === t.spend));
    return cs.length ? `<optgroup label="${esc(GROUP_LABEL[g])}">${cs.map((c) => `<option value="${esc(c.id)}" ${t.spend === c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</optgroup>` : "";
  }).join("");
  const facet = (key) => FACET[key].values.map((v) => [v, FACET[key].names[v], facetMark(key, v, "xs")]);
  const auto = (label) => ["auto", label, ibox(ic("refresh"), "var(--muted)", "xs")];
  return {
    title: `${facetMark("inst", a.institution)}<span>${esc(a.name)}</span>`,
    body: `
      <label class="field" for="acc-name">Nom<input id="acc-name" maxlength="60" autocomplete="off" value="${esc(t.name)}"></label>
      <p class="hint">${esc(a.institution)} · ${esc(KIND[a.kind] || a.kind)}${a.iban ? ` · ${esc(a.iban)}` : ""}</p>
      <h3 class="field">Objectif</h3>
      ${radio("goal", facet("goal"), t.goal)}
      <h3 class="field">Disponibilité</h3>
      ${radio("availability", [auto(`Selon le type (${facetName("liq", a.availability_auto).toLowerCase()})`), ...facet("liq")], t.availability)}
      <h3 class="field">Catégorie</h3>
      ${radio("category", [auto("Selon chaque ligne"), ...facet("cat")], t.category)}
      <p class="hint">« Selon chaque ligne » range les liquidités, les fonds et les cryptos du compte chacun à sa place. Une catégorie choisie s'applique à tout le compte.</p>
      <label class="field" for="acc-spend">Dépenses de ce compte<select id="acc-spend" class="select-full"><option value="" ${t.spend ? "" : "selected"}>Selon les règles habituelles</option>${spendOpts}</select></label>
      <p class="hint">Pour une poche dédiée (vacances, voiture) : toutes ses sorties vont dans cette catégorie, celles déjà importées comme les prochaines. Les virements vers tes autres comptes restent des virements, et une catégorie choisie à la main reste la sienne.</p>
      <div class="setrow"><span id="acc-hide-lbl">Masquer ce compte<small>Il disparaît du patrimoine et de l'accueil. Ses relevés continuent d'arriver et rien n'est effacé.</small></span><button class="switch" type="button" role="switch" aria-checked="${t.hidden}" aria-labelledby="acc-hide-lbl" data-a="acc-pick" data-v="hidden|${!t.hidden}"></button></div>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}`,
    foot: `<button class="primary" type="button" data-a="acc-save" ${diff && Object.keys(diff).length && !sh.busy ? "" : "disabled"}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  if (e.target.id !== "acc-name" || SH.kind !== "account" || !SH.tmp) return;
  SH.tmp.name = e.target.value;
  renderSheet();
});

document.addEventListener("change", (e) => {
  if (e.target.id !== "acc-spend" || SH.kind !== "account" || !SH.tmp) return;
  SH.tmp.spend = e.target.value;
  renderSheet();
});

// --- carte « Comptes » des réglages ------------------------------------------------------------

export function accountsList() {
  const fe = store.use(FRESH), ae = store.use(ACCOUNTS);
  const err = [fe, ae].find((x) => x.status === "error");
  if (err) return fill($("fresh-list"), `<div class="empty">Impossible de charger : ${esc(err.error.message)}</div>`);
  if (!fe.data || !ae.data) return fill($("fresh-list"), '<div class="empty">Chargement…</div>');
  if (!fe.data.items.length) return fill($("fresh-list"), '<div class="empty">Aucun compte pour l\'instant.</div>');
  setInstitutions(ae.data.items.map((a) => a.institution));
  const byId = Object.fromEntries(ae.data.items.map((a) => [a.id, a]));
  const items = fe.data.items.slice().sort((x, y) => (x.institution || "").localeCompare(y.institution || "", "fr") || x.name.localeCompare(y.name, "fr"));
  fill($("fresh-list"), items.map((f) => {
    const a = byId[f.account_id];
    const age = daysSince(f.last_data);
    const stale = age == null || age > STALE_DAYS;
    const sub = f.last_data
      ? `données au ${date(f.last_data)}${f.last_import ? ` · importé le ${date(f.last_import.slice(0, 10))}` : ""}`
      : "aucune donnée importée";
    return `<button class="row" type="button" data-a="acc-edit" data-v="${esc(f.account_id)}" aria-label="${esc(f.name)}, ${esc(sub)}${f.hidden ? ", masqué" : ""}. Modifier">
      ${facetMark("inst", f.institution || (a && a.institution) || "?")}
      <span class="row-main"><span class="row-title">${esc(f.name)}</span><span class="row-sub">${esc(f.institution || "")} · ${esc(sub)}</span></span>
      <span class="row-num">${f.hidden ? '<span class="pill">masqué</span>' : ""}<span class="pill ${stale ? "warn" : "ok"}">${age == null ? "—" : `${age} j`}</span></span></button>`;
  }).join(""));
}

export const actions = {
  "acc-edit": (id) => openSheet("account", id),
  "acc-pick": (v) => {
    if (!SH.tmp) return;
    const [k, val] = v.split("|");
    SH.tmp[k] = k === "hidden" ? val === "true" : val;
    renderSheet();
  },
  "acc-save": async () => {
    const a = find(SH.arg);
    if (!a) return;
    const name = $("acc-name");
    if (name) SH.tmp.name = name.value;
    const diff = changes(a, SH.tmp);
    if (!diff || !Object.keys(diff).length) return;
    if ("name" in diff) diff.name = diff.name.trim();
    const items = [];
    if ("spend" in diff) {
      // une seule règle « tout débit » par compte : l'ancienne s'éteint, la nouvelle la remplace
      if (a.spend_rule) items.push(["disable_rule", { rule_id: a.spend_rule.rule_id }]);
      if (diff.spend) items.push(["create_rule", { pattern: "", direction: "debit", category_id: diff.spend, account_id: a.id, priority: SPEND_PRIORITY }]);
      delete diff.spend;
    }
    if (Object.keys(diff).length) items.unshift(["edit_account", { account_id: a.id, ...diff }]);
    SH.busy = true;
    SH.err = "";
    renderSheet();
    try {
      const [text, bad] = outcome(await proposeAndApprove(items));
      if (bad) SH.err = text;
      else {
        closeSheet();
        toast(diff.hidden === true ? `« ${a.name} » est masqué` : "Compte enregistré");
      }
    } catch (e) {
      SH.err = failure(e);
    } finally {
      SH.busy = false;
      if (SH.kind) renderSheet();
    }
  },
};
