// Patrimoine : prix de revient des cryptos, commun à tous tes comptes crypto (un envoi d'un compte
// à l'autre garde son coût, une récompense entre sans coût). La page d'une crypto le lit.
import { paths } from "./wstate.js";
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
