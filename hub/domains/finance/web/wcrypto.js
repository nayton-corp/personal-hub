// Patrimoine : résultat des cryptos depuis l'achat (comme CoinStats), en francs ou en dollars.
// Le serveur tient un prix de revient par crypto commun à tous tes comptes crypto : un envoi
// d'un compte à l'autre garde son coût, une récompense entre sans coût. En francs, le résultat
// se partage entre l'effet des cryptos et l'effet du dollar. Ce que le calcul ne sait pas lire
// (parts sans historique) est montré, jamais compté en silence.
import { amount, esc } from "../../ui.js";
import { base } from "../../format.js";
import { sgnMoney } from "./wchart.js";
import { units } from "./perf.js";
import { paths } from "./wstate.js";
import { store } from "../../store.js";

export const CCY = { v: "base" }; // "base" (francs) ou "USD"

const tone = (v) => (v == null || Math.abs(v) < 0.5 ? "zero" : v > 0 ? "pos" : "neg");
const cell = (label, v, ccy, hint = "") => `<div><span>${label}</span><b class="num ${tone(v)}"><span class="money">${v == null ? "—" : sgnMoney(v)}</span>${v == null ? "" : ` <small>${esc(ccy)}</small>`}</b>${hint}</div>`;

export function since() {
  const h = store.data(paths.holdings);
  return h && h.crypto ? h.crypto.since_purchase : null;
}

// la section de l'écran Patrimoine quand la sélection ne contient que des comptes crypto
export function cryptoSection(sel) {
  const r = since();
  if (!r || !sel.length || !sel.every((l) => l.kind === "crypto")) return "";
  const usd = CCY.v === "USD" && r.result_usd;
  const seg = `<div class="seg small" role="group" aria-label="Devise du résultat">${[["base", base()], ["USD", "USD"]].map(([k, l]) => `<button type="button" data-a="w-ccy" data-v="${k}" aria-pressed="${CCY.v === k}"${k === "USD" && !r.result_usd ? " disabled" : ""}>${l}</button>`).join("")}</div>`;
  let body;
  if (usd) {
    body = `<div class="strip">${cell("Résultat", units(r.result_usd), "USD")}</div>
      <p class="pnote">Chaque achat et chaque vente au change de son jour, la valeur au change d'aujourd'hui : c'est le chiffre à comparer avec CoinStats.</p>`;
  } else {
    const fx = r.fx_effect ? units(r.fx_effect) : null;
    body = `<div class="strip">${cell("Résultat", units(r.result), base())}${cell("Dû aux cryptos", r.crypto_effect ? units(r.crypto_effect) : null, base())}${cell("Dû au dollar", fx, base())}</div>
      <div class="strip">${cell("Latent", units(r.unrealized), base())}${cell("Réalisé", units(r.realized), base())}<div><span>Prix de revient</span><b class="num">${amount(units(r.cost))}</b></div></div>
      ${units(r.income) >= 0.5 ? `<p class="pnote">Dont récompenses reçues (staking, Earn) : ${amount(units(r.income))} à leur arrivée, comptées sans coût.</p>` : ""}`;
  }
  const gaps = [];
  if (units(r.unknown_cost_value) >= 1) gaps.push(`${amount(units(r.unknown_cost_value))} de cryptos sans historique d'achat, comptées sans gain ni perte`);
  if (units(r.arrived_from_outside) >= 1) gaps.push(`${amount(units(r.arrived_from_outside))} arrivés d'un compte que le hub ne suit pas, au cours du jour d'arrivée`);
  if (units(r.unexplained_out_cost) >= 1) gaps.push(`${amount(units(r.unexplained_out_cost))} de prix de revient retirés pour des parts parties sans trace`);
  if (r.missing_prices) gaps.push("des cryptos sans cours, laissées de côté");
  const note = gaps.length ? `<p class="pnote">À savoir : ${gaps.join(" ; ")}.</p>` : "";
  return `<section class="section" aria-labelledby="t-since"><div class="section-head"><h2 class="section-title" id="t-since">Depuis l'achat</h2>${seg}</div>
    ${body}${note}<p class="hint">Tous tes comptes crypto ensemble. Un envoi d'un compte à l'autre garde son prix d'achat. La performance plus haut mesure la période choisie.</p></section>`;
}

// la page d'une crypto, tous comptes : prix de revient et résultat depuis l'achat
export function assetSince(key) {
  const r = since();
  return r && r.by_asset ? r.by_asset[key] || null : null;
}
