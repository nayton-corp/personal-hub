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
