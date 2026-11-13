// Première visite : le premier quart d'heure dans Finance, en six étapes lues dans les données
// (rien n'est retenu à part, sauf « Terminer »). Sans aucun compte, la mise en route prend tout
// l'Aperçu ; ensuite elle tient en une carte, jusqu'à ce que tout soit fait ou qu'on la ferme.
import { SHEETS, esc, ibox, ic, pref } from "../../ui.js";
import { model } from "./bmodel.js";
import { budgetPath } from "./budget.js";
import { store } from "../../store.js";

const PATHS = { acc: "/finance/accounts", goods: "/finance/goods", debts: "/finance/debts", packs: "/finance/rules/packs", keys: "/auth/passkeys" };

// [fait, icône, titre, pourquoi, action, valeur] ; null tant que tout n'est pas arrivé
function steps() {
  const d = Object.fromEntries(Object.entries(PATHS).map(([k, p]) => [k, store.use(p).data]));
  const b = store.use(budgetPath(store.today, "m")).data;
  if (Object.values(d).some((x) => !x) || !b) return null;
  const n = d.acc.items.length;
  return [
    [n > 0, "wallet", "Ajouter un premier compte", "ta banque, par fichier ou par connexion", "rubric", "add-account"],
    [n > 1, "layers", "Ajouter tes autres comptes", "épargne, 3a, titres, crypto : le patrimoine entier", "rubric", "add-account"],
    [d.goods.items.length + d.debts.items.length > 0, "home", "Ce qui n'est sur aucun compte", "logement, voiture, crédit, hypothèque", "rubric", "accounts"],
    [d.packs.active_rules > 0, "list", "Classer tes dépenses", "des règles de départ rangent les achats courants", "tab", "journal"],
    [model(b).T != null, "piggy", "Fixer ton budget", "ce que tu veux dépenser par mois, par catégorie", "tab", "budget"],
    [d.keys.items.length >= 2, "faceid", "Une passkey de secours", "si ce téléphone se perd", "fv-hub", "security"],
  ];
}

const list = (ss) => `<div class="list fv-list">${ss.map(([done, icon, t, s, a, v], i) => `<button class="row fv-row${done ? " done" : ""}" type="button" data-a="${a}" data-v="${v}">
  ${ibox(ic(done ? "check" : icon), done ? "var(--pos)" : "var(--accent)")}<span class="row-main"><span class="row-title">${i + 1}. ${esc(t)}</span><span class="row-sub">${esc(s)}</span></span>
  <span class="go">${done ? "" : ic("chev")}</span></button>`).join("")}</div>`;

// { full } : l'écran entier (aucun compte) ; { card } : la carte de l'Aperçu ; null : rien à dire
export function firstVisit() {
  if (pref("fv.done", false)) return null;
  const ss = steps();
  if (!ss) return null;
  const left = ss.filter(([done]) => !done).length, total = ss.length;
  if (!left) return null;
  if (!ss[0][0]) {
    return { full: `<section class="fv" aria-labelledby="t-fv"><h2 id="t-fv">Bienvenue dans Finance</h2>
      <p>Six étapes, un quart d'heure : ton patrimoine complet et un budget qui se suit tout seul. Tes données restent chez toi.</p>
      ${list(ss)}<button class="primary" type="button" data-a="rubric" data-v="add-account">Ajouter mon premier compte</button></section>` };
  }
  return { card: `<div class="sumcards"><button class="sumcard wide fv-card" type="button" data-a="fv-open" aria-haspopup="dialog">
    <span class="l">Mise en route${ic("chev")}</span><span class="v">${total - left} sur ${total}</span>
    <span class="pbar thin"><i data-css="width:${(((total - left) / total) * 100).toFixed(0)}%"></i></span>
    <span class="s">Ensuite : ${esc(ss.find(([done]) => !done)[2].toLowerCase())}</span></button></div>` };
}

SHEETS.firstvisit = () => {
  const ss = steps();
  if (!ss) return null;
  return { title: "Mise en route", body: list(ss), foot: '<button class="secondary" type="button" data-a="fv-done">Terminer, ne plus afficher</button>' };
};
