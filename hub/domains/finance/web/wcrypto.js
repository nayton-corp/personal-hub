// Patrimoine : prix de revient des cryptos, commun à tous tes comptes crypto (un envoi d'un compte
// à l'autre garde son coût, une récompense entre sans coût). La page d'une crypto le lit.
import { paths, sum } from "./wstate.js";
import { sinceBuy } from "./wcurve.js";
import { units } from "./perf.js";
import { store } from "../../store.js";

export function since() {
  const h = store.data(paths.holdings);
  return h && h.crypto ? h.crypto.since_purchase : null;
}

// la page d'une crypto, tous comptes : prix de revient et résultat depuis l'achat
export function assetSince(key) {
  const r = since();
  return r && r.by_asset ? r.by_asset[key] || null : null;
}

// le gain depuis l'achat d'un groupe de lignes (sinceBuy) : une crypto tous comptes lit le prix de
// revient commun (`pool`, un envoi entre tes comptes garde son coût) ; sinon chaque position doit
// avoir le sien. Les liquidités, dettes et biens n'en ont pas.
export function buyGain(ls, pool = null) {
  if (pool) return sinceBuy(null, units(pool.cost), units(pool.unrealized));
  const pos = ls.filter((l) => l.isin);
  if (!pos.length || pos.some((l) => l.cost == null)) return null;
  return sinceBuy(sum(pos), pos.reduce((t, l) => t + l.cost, 0));
}
