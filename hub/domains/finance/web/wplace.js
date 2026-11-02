// Patrimoine : les soldes qu'aucune opération connue n'explique (le rapprochement,
// docs/finance-politique.md). Une ligne sous le grand chiffre, comme « Fin de courbe estimée »,
// ouvre la liste chiffrée : compte, actif, montant et cause. Un écart qu'aucun import ne comblera
// se règle d'un geste : « J'ai payé X », « Garder tel quel » (au cours du jour où le hub l'a vu) ou,
// pour un envoi, « Parti hors de mes comptes ». Ta décision est gardée. Rien n'est compté en silence.
// Tout vient de /finance/breaks, en centimes.
import { SHEETS, amount, closeSheet, esc, failure, ic, openSheet, toast } from "../../ui.js";
import { api, store } from "../../store.js";
import { base, date } from "../../format.js";
import { go } from "../../shell.js";
import { units } from "./perf.js";

export const breaksPath = "/finance/breaks";

const NAME = {
  "unexplained+": (s) => `${s} sans historique d'achat`,
  "unexplained-": (s) => `${s} : des sorties que l'historique ne montre pas`,
  sent_outside: (s) => `${s} envoyés vers un portefeuille non suivi`,
  arrived_outside: (s) => `${s} arrivés d'un portefeuille non suivi`,
  no_price: (s) => `${s} sans cours`,
  stale_price: (s) => `Cours ancien : ${s}`,
};
const CAUSE = {
  no_history: "aucun achat ni arrivée connus (souvent un historique que le hub n'a pas pu lire)",
  missing_out: "une sortie n'a pas été lue",
  untracked_wallet: "l'autre côté est un portefeuille que le hub ne suit pas",
  no_price: "aucun cours connu, hors du patrimoine",
  stale: "dernier cours trop ancien",
};
const key = (b) => (b.kind === "unexplained" ? `unexplained${Number(b.quantity) >= 0 ? "+" : "-"}` : b.kind);
const worth = (b) => (b.value ? Math.abs(units(b.value)) : 0);

function itemsFor(accs) {
  const r = store.use(breaksPath).data;
  if (!r || !r.items.length) return [];
  return accs ? r.items.filter((b) => accs.has(b.account_id)) : r.items;
}
let shown = null; // les comptes de la ligne affichée, pour la liste

// la ligne d'avertissement sous le grand chiffre, pour les comptes de la sélection
export function breaksLine(sel) {
  shown = new Set((sel || []).map((l) => l.acc));
  const items = itemsFor(shown);
  if (!items.length) return "";
  const total = items.reduce((t, b) => t + worth(b), 0);
  return `<button class="warnline" type="button" data-a="w-brk"><span>${ic("alert")}</span><span>${items.length} solde${items.length > 1 ? "s" : ""} non expliqué${items.length > 1 ? "s" : ""} · ${amount(total)}</span></button>`;
}

SHEETS.brk = () => {
  const items = itemsFor(shown);
  if (!items.length) return { title: "Tout est expliqué", body: '<p class="note">Chaque solde vient d\'une opération connue.</p>' };
  return {
    title: "Soldes non expliqués",
    body: `<p class="note">Ces montants ne viennent d'aucune opération connue. Ils restent hors du gain jusqu'à ce que l'historique manquant soit importé.</p>
      <div class="list">${items.map((b) => `<button class="row row2 go-row" type="button" data-a="w-brk-one" data-v="${esc(b.id)}"><span class="row-main"><span class="row-title">${esc(NAME[key(b)](b.symbol))}</span><span class="row-sub">${esc(b.account)} · depuis le ${date(b.since)} · ${esc(CAUSE[b.cause] || "")}</span></span>
        <span class="row-num"><span class="row-val num">${b.value ? amount(worth(b)) : "—"}</span></span><span class="go">${ic("chev")}</span></button>`).join("")}</div>`,
    foot: '<button class="primary" type="button" data-a="w-brk-conn">Ouvrir les connexions</button>',
  };
};

// un écart : son montant, sa cause et les gestes qui le règlent
const DO = { accept: "Garder tel quel", gone: "Parti hors de mes comptes" };
SHEETS.brk1 = (id) => {
  const b = itemsFor(null).find((x) => x.id === id);
  if (!b) return { title: "Écart réglé", body: '<p class="note">Cet écart n\'est plus ouvert.</p>' };
  const qty = b.quantity ? `${esc(b.quantity.replace(".", ","))} ${esc(b.symbol)} sur ${esc(b.account)}` : esc(b.account);
  const cost = b.actions.includes("cost")
    ? `<label class="field" for="brk-cost">J'ai payé, en ${base()}<input id="brk-cost" inputmode="decimal" autocomplete="off"></label><div class="acts"><button class="primary" type="button" data-a="w-brk-cost" data-v="${esc(b.id)}">Valider ce prix d'achat</button></div>`
    : "";
  const keep = b.kind === "unexplained" && Number(b.quantity) > 0 ? "<p class=\"hint\">« Garder tel quel » : le prix d'achat devient la valeur du jour où le hub a vu ces parts.</p>" : "";
  const acts = b.actions.filter((a) => DO[a]).map((a) => `<button class="secondary" type="button" data-a="w-brk-do" data-v="${esc(`${a}|${b.id}`)}">${DO[a]}</button>`).join("");
  return {
    title: NAME[key(b)](b.symbol),
    body: `<div class="strip"><div><span>Montant</span><b class="num">${b.value ? amount(worth(b)) : "inconnu"}</b></div></div><p class="note">${qty}, depuis le ${date(b.since)} : ${esc(CAUSE[b.cause] || "")}.</p>${cost}${keep}`,
    foot: `<div class="stack-v">${acts}<button class="secondary" type="button" data-a="w-brk-conn">Importer l'historique (Connexions)</button></div>`,
  };
};

async function decide(id, decision, cost) {
  try {
    await api(`${breaksPath}/decide`, { id, decision, ...(cost != null ? { cost_minor: cost } : {}) });
    closeSheet();
    store.invalidate();
    toast("Écart réglé");
  } catch (e) {
    toast(failure(e), { error: true });
  }
}

export const actions = {
  "w-brk": () => openSheet("brk"),
  "w-brk-one": (v) => openSheet("brk1", v),
  "w-brk-do": (v) => { const i = v.indexOf("|"); decide(v.slice(i + 1), v.slice(0, i)); },
  "w-brk-cost": (v) => {
    const raw = (document.getElementById("brk-cost") || {}).value || "";
    const n = Number(raw.replace(/['’\s]/g, "").replace(",", "."));
    if (!raw || !Number.isFinite(n) || n < 0) return toast("Montant invalide", { error: true });
    decide(v, "cost", Math.round(n * 100));
  },
  "w-brk-conn": () => { closeSheet(true); go("sources", { rubric: "conn" }); },
};
