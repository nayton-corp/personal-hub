// La carte « À valider » d'une stratégie repérée par le hub (strategy_detect.py) : ce qu'il a vu
// au journal, échéance par échéance, et les garde-fous remplis. Rien n'est deviné ici : les
// chiffres viennent de l'aperçu de la proposition (`details.detected`).
import { base, decimals } from "../../format.js";
import { esc, ic, n0, n2 } from "../../ui.js";
import { roundMoney } from "./smodel.js";

const SHOWN = 12; // les dernières échéances, une barre chacune
const MONTHS = ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "août", "sep", "oct", "nov", "déc"];
const cash = (minor) => roundMoney(minor, decimals(), base(), n0, n2);
const fr = (iso) => iso.split("-").reverse().join(".");
const label = (iso, weekly) => (weekly ? `${Number(iso.slice(8))}.${Number(iso.slice(5, 7))}` : MONTHS[Number(iso.slice(5, 7)) - 1]);

function bars(periods, weekly) {
  const last = periods.slice(-SHOWN), top = Math.max(1, ...last.map((x) => x.done));
  return `<div class="seen-bars" aria-hidden="true">${last.map((x) => `<span><i style="height:${Math.max(3, Math.round((38 * x.done) / top))}px"${x.done ? "" : ' class="none"'}></i>${esc(label(x.due, weekly))}</span>`).join("")}</div>`;
}

// le détail sous la carte ; vide pour toute autre proposition
export function seenDetail(p) {
  const d = p.kind === "save_strategy" && p.preview.details && p.preview.details.detected;
  if (!d) return "";
  const weekly = d.cadence === "weekly", periods = d.periods || [];
  const what = d.account ? ["versement", "versements"] : ["achat", "achats"];
  const last = periods.length ? periods[periods.length - 1].due : d.since;
  const n = d.count ?? d.kept;
  const checks = [
    `<b>${n} ${n > 1 ? what[1] : what[0]} d'affilée</b>, ${weekly ? "un par semaine" : "un par mois"}`,
    d.low != null ? `<b>Montants proches</b> : ${cash(d.low)} à ${cash(d.high)} (±15 % au plus)` : "",
    `<b>Toujours en cours</b> : dernière échéance le ${fr(last)}`,
    d.account ? "<b>Aucun retrait</b> pendant la série" : "<b>Aucune vente</b> pendant la série",
  ].filter(Boolean);
  return `<div class="prop-more seen" role="group" aria-label="Ce que le hub a vu">
    <p class="seen-lbl">Ce que le hub a vu au journal</p>${bars(periods, weekly)}
    <ul class="seen-checks">${checks.map((c) => `<li>${ic("check")}<span>${c}</span></li>`).join("")}</ul>
    ${p.preview.details.phrase ? `<p class="strat-say big">${esc(p.preview.details.phrase)}</p>` : ""}
    <p class="hint">Tes échéances passées comptent déjà. Ensuite, un seul rappel si ${d.account ? "le versement" : "l'achat"} n'est pas au journal trois jours après l'échéance.</p>
    <p class="hint">« Refuser » veut dire : ce n'est pas une stratégie. Le hub ne la reproposera pas, sauf si ton montant ou ton rythme change nettement.</p>
  </div>`;
}
