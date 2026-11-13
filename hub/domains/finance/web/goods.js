// Biens hors comptes : logement, véhicule, objet de valeur, prêt accordé. Un bien n'a ni relevé
// ni cours : sa valeur est saisie à une date, puis suit sa variation annuelle s'il en a une
// (une voiture perd 15 % par an). Le patrimoine le compte, le rendement l'ignore. Tout
// s'enregistre avec un seul Face ID (proposition `save_good`).
import { SH, SHEETS, amount2, closeSheet, esc, failure, fill, ibox, ic, openSheet, renderSheet, toast } from "../../ui.js";
import { date, toMinor, units } from "../../format.js";
import { outcome, proposeAndApprove } from "./proposals.js";
import { store } from "../../store.js";

const $ = (id) => document.getElementById(id);
export const GOODS = "/finance/goods";
export const GOOD_KIND = { home: "Logement", vehicle: "Véhicule", object: "Objet de valeur", loan: "Prêt accordé", other: "Autre bien" };
const KIND_IC = { home: "home", vehicle: "car", object: "gift", loan: "user", other: "layers" };
// la décote proposée à la création : elle se change, ou s'efface
const USUAL = { home: "", vehicle: "-15", object: "", loan: "", other: "" };
export const goodMark = (g, size = "") => ibox(ic(KIND_IC[g.kind] || "layers"), "var(--s5)", size);

const today = () => new Date().toISOString().slice(0, 10);
const find = (id) => ((store.data(GOODS) || {}).items || []).find((g) => g.id === id) || null;
// « 12'500,50 » → centimes ; "" → null ; illisible → NaN
function minor(s) {
  const t = String(s ?? "").replace(/['’\s]/g, "").replace(",", ".");
  if (!t) return null;
  return /^\d+(\.\d{1,2})?$/.test(t) ? toMinor(t) : NaN;
}

function initial(g) {
  if (!g) return { name: "", kind: "home", value: "", on: today(), change: USUAL.home };
  return { name: g.name, kind: g.kind, value: "", on: today(), change: g.yearly_change_pct || "" };
}

// paramètres de save_good : tout pour une création, les seuls champs changés sinon
function params(g, t) {
  const out = g ? { good_id: g.id } : {};
  const name = t.name.trim();
  if (!name) throw new Error("Donne un nom à ce bien");
  if (!g || name !== g.name) out.name = name;
  if (!g || t.kind !== g.kind) out.kind = t.kind;
  const change = String(t.change || "").replace(",", ".").replace("−", "-").trim();
  if (change && !/^-?\d{1,2}(\.\d{1,2})?$/.test(change)) throw new Error("Variation illisible (en % par an, par exemple -15)");
  if (g ? (change || "0") !== (g.yearly_change_pct || "0") : change) out.yearly_change_pct = change || "0";
  const v = minor(t.value);
  if (Number.isNaN(v)) throw new Error("Montant illisible");
  if (!g && !v) throw new Error("Donne sa valeur aujourd'hui");
  if (v != null) Object.assign(out, { value_minor: v, value_on: t.on || today() });
  if (g && Object.keys(out).length === 1) throw new Error("Rien n'a changé");
  return out;
}

const input = (k, label, t, attrs = "") => `<label class="field" for="good-${k}">${label}
  <input id="good-${k}" data-k="${k}" value="${esc(t[k])}" autocomplete="off" ${attrs}></label>`;

SHEETS.good = (id, sh) => {
  const g = id ? find(id) : null;
  if (id && !g) return null;
  if (!sh.tmp) sh.tmp = initial(g);
  const t = sh.tmp;
  const kinds = Object.entries(GOOD_KIND).map(([k, l]) => `<button type="button" role="radio" aria-checked="${t.kind === k}" data-a="good-kind" data-v="${k}">
    ${goodMark({ kind: k }, "xs")}${l}</button>`).join("");
  const now = g ? `<p class="hint">Vaut ${amount2(units(g.value))} ${esc(g.currency)} aujourd'hui, d'après la valeur du ${date(g.stated_on)}.</p>` : "";
  return {
    title: g ? esc(g.name) : "Ajouter un bien",
    body: `${input("name", "Nom", t, 'placeholder="Appartement, voiture, montre…" maxlength="60"')}
      <h3>Genre</h3><div class="catgrid" role="radiogroup" aria-label="Genre">${kinds}</div>
      ${now}
      <div class="jf-pair">${input("value", g ? "Nouvelle valeur" : "Valeur", t, 'inputmode="decimal" placeholder="0.00"')}
      ${input("on", "À la date du", t, `type="date" max="${today()}"`)}</div>
      ${input("change", "Variation par an, en % (facultatif)", t, 'inputmode="text" placeholder="-15 pour une voiture"')}
      <p class="hint">Compté dans ton patrimoine, jamais dans ton rendement : une estimation n'est ni un gain ni une perte.</p>
      ${sh.err ? `<div class="err" role="alert">${esc(sh.err)}</div>` : ""}
      ${g && !g.closed_on ? `<button class="link-row danger" type="button" data-a="good-close" data-v="${esc(g.id)}">Je ne l'ai plus (vendu, donné, remboursé)${ic("chev")}</button>` : ""}`,
    foot: `<button class="primary" type="button" data-a="good-save" ${sh.busy ? "disabled" : ""}>${ic("faceid")}${sh.busy ? "Validation…" : "Enregistrer avec Face ID"}</button>`,
  };
};

document.addEventListener("input", (e) => {
  const k = e.target.dataset && e.target.dataset.k;
  if (k && e.target.id === `good-${k}` && SH.kind === "good" && SH.tmp) SH.tmp[k] = e.target.value;
});

// les biens, dans « Comptes et biens »
export function goodsList() {
  const box = $("good-list");
  if (!box) return;
  const ge = store.use(GOODS);
  if (ge.status === "error") return fill(box, `<div class="empty">Impossible de charger : ${esc(ge.error.message)}</div>`);
  if (!ge.data) return fill(box, '<div class="empty">Chargement…</div>');
  if (!ge.data.items.length) return fill(box, '<div class="empty">Aucun bien. Ajoute ton logement, ta voiture ou un prêt accordé : ils comptent dans ton patrimoine.</div>');
  fill(box, ge.data.items.map((g) => {
    const sub = g.closed_on ? `sorti le ${date(g.closed_on)}` : `${GOOD_KIND[g.kind]}${g.yearly_change_pct ? ` · ${g.yearly_change_pct} % par an` : ""} · valeur du ${date(g.stated_on)}`;
    return `<button class="row" type="button" data-a="good-edit" data-v="${esc(g.id)}" aria-label="${esc(g.name)}, ${esc(sub)}. Modifier">
      ${goodMark(g)}<span class="row-main"><span class="row-title">${esc(g.name)}</span><span class="row-sub">${esc(sub)}</span></span>
      <span class="row-num"><span class="row-val num">${amount2(units(g.value))}</span></span></button>`;
  }).join(""));
}

// détail d'un bien dans le patrimoine
export function goodDetail(id) {
  const g = find(id);
  if (!g) return "";
  return `<div class="sub-head"><span>${esc(GOOD_KIND[g.kind])}</span><button class="linkish" type="button" data-a="good-edit" data-v="${esc(g.id)}">Modifier</button></div>
    <dl class="dl"><dt>Valeur aujourd'hui</dt><dd>${amount2(units(g.value))} ${esc(g.currency)}</dd>
      <dt>Saisie le ${date(g.stated_on)}</dt><dd>${amount2(units(g.stated))} ${esc(g.currency)}</dd>
      ${g.yearly_change_pct ? `<dt>Variation</dt><dd>${esc(g.yearly_change_pct)} % par an</dd>` : ""}</dl>
    <p class="hint">Compté dans le patrimoine, pas dans le rendement.</p>`;
}

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
  "good-add": () => { store.use(GOODS); openSheet("good", null); },
  "good-edit": (id) => openSheet("good", id),
  "good-kind": (v) => {
    const t = SH.tmp;
    if (!SH.arg && (t.change === USUAL[t.kind] || !t.change)) t.change = USUAL[v];
    t.kind = v;
    renderSheet();
  },
  "good-save": () => {
    const g = SH.arg ? find(SH.arg) : null;
    let p;
    try { p = params(g, SH.tmp); } catch (e) { SH.err = e.message; return renderSheet(); }
    return send([["save_good", p]], g ? "Bien mis à jour" : "Bien ajouté à ton patrimoine");
  },
  "good-close": (id) => send([["save_good", { good_id: id, closed_on: today() }]], "Bien sorti du patrimoine"),
};
