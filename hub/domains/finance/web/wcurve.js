// Patrimoine : le pas de la courbe, sans rien lire d'autre que des dates. Chaque jour jusqu'à six
// mois, puis chaque dimanche : une année tient en une cinquantaine de points, calés sur le
// calendrier. Au-delà de 400 points le serveur élargit lui-même le pas (semaine, puis mois).
const DAILY_MAX = 190;
const t = (s) => Date.parse(`${s}T00:00:00Z`);
const gap = (a, b) => Math.round((t(b) - t(a)) / 864e5);

export const stepFor = (from, to) => (from && to && gap(from, to) > DAILY_MAX ? "week" : "day");

// l'écart le plus courant entre deux points : le premier et le dernier intervalle sont plus courts
// (la période ne commence pas un dimanche), ils ne décident pas du mot
export function granLabel(pts) {
  if (pts.length < 2) return "";
  const gaps = pts.slice(1).map((p, k) => gap(pts[k].d, p.d)).sort((a, b) => a - b);
  const s = gaps[gaps.length >> 1];
  return s <= 1 ? "par jour" : s === 7 ? "par semaine" : s >= 28 && s <= 31 ? "par mois" : `tous les ${s} jours`;
}

// identifiant d'une ligne pour /finance/performance : « compte|ISIN », « compte|cash », « debt:… »
// une dette ou un bien hors comptes : une ligne à elle seule, sans compte
export const lone = (l) => l.kind === "debt" || l.kind === "good";
export const lineId = (l) => (lone(l) ? l.asset : l.asset.startsWith("isin:") ? `${l.acc}|${l.asset.slice(5)}` : `${l.acc}|cash`);

// Ce que l'écran demande à /finance/performance pour la sélection `sel`, parmi les lignes `every`
// de l'app. L'app ne connaît que les lignes d'aujourd'hui : un compte dont elles sont toutes
// choisies est demandé en entier (`account=`), et le serveur y joint les positions vendues depuis.
// Sans cela une vente efface le passé du gain et du rendement. `narrow` (un actif choisi) : rien
// de plus que les lignes nommées. « compte|cash » porte aussi les revenus et frais du compte.
export function perfSel(sel, every, narrow = false) {
  const count = (ls) => {
    const m = new Map();
    for (const l of ls) if (!lone(l)) m.set(l.acc, (m.get(l.acc) || 0) + 1);
    return m;
  };
  const have = count(every), got = count(sel);
  const accounts = new Set(), ids = new Set();
  for (const l of sel) {
    if (lone(l)) ids.add(l.asset);
    else if (!narrow && got.get(l.acc) === have.get(l.acc)) accounts.add(l.acc);
    else ids.add(lineId(l)).add(`${l.acc}|cash`);
  }
  const q = (k, xs) => [...xs].sort().map((x) => `&${k}=${encodeURIComponent(x)}`).join("");
  return q("account", accounts) + q("line", ids);
}

// Le pourcentage à côté d'un gain en francs : le rendement de l'argent engagé, jamais le rendement
// pondéré dans le temps, qui ignore les montants et contredit les francs. Jusqu'à un an : celui de
// la période (`personal` du serveur : le gain rapporté au capital moyen, chaque apport compté
// depuis son jour). Au-delà : le taux annuel exact (`mwr` du résumé), que le serveur ne calcule
// que pour la période entière. Quand ces taux se taisent (l'argent est arrivé tard dans la
// période, le doigt sur une courbe de plus d'un an), `stake` : le gain rapporté à l'argent mis en
// jeu (`on_stake` du serveur), sur la période, pas par an, nommé comme tel (`rateWord`). Sans
// argent mis en jeu, les francs seuls.
export function moneyRate(period, days, yearly = null, stake = null) {
  if (days <= 366 && period != null) return { v: period, yr: false };
  if (days > 366 && yearly != null) return { v: yearly, yr: true };
  return stake == null ? null : { v: stake, yr: false, put: true };
}

// les mots après le pourcentage de moneyRate
export const rateWord = (mine) => (!mine ? "" : mine.yr ? " par an" : mine.put ? " de l'argent placé" : "");

// Le gain d'une ligne de la liste ou d'une position : depuis l'achat (valeur − prix de revient), comme
// les apps de placement, quelle que soit la période choisie en haut (16/11 : le % d'une période,
// rapporté au capital moyen, s'envolait sur une ligne vendue puis rachetée). `latent` :
// le gain déjà calculé (une crypto tous comptes : celui des parts dont l'achat est connu). Sans
// prix de revient connu et positif, rien : ni francs ni pastille plutôt qu'un chiffre faux.
export function sinceBuy(value, cost, latent = null) {
  if (cost == null || !(cost > 0)) return null;
  const gain = latent ?? value - cost;
  return { gain, pct: gain / cost };
}

// Sans prix de revient (un compte de prévoyance, un compte bancaire, une position dont l'achat
// n'est pas au registre) : le gain depuis l'ouverture, valeur − versements nets, sur toute
// l'histoire (`start` : la valeur du premier jour, `flows` : les apports nets depuis). Le % se
// rapporte à l'argent versé ; sans argent versé, les francs seuls.
export function sinceStart(gain, start, flows) {
  const put = start + flows;
  return { gain, pct: put > 0 ? gain / put : null };
}
