// @ts-check
// La barre du bas change de boutons en changeant d'espace : un double toucher tomberait, au même
// endroit, sur le bouton redessiné sous le doigt (Finance, puis Journal). Le second toucher, au
// même endroit et juste après le changement, est ignoré.

/** @type {string | null | undefined} */
let barOf;
let swapped = 0;
let last = { x: -99, y: -99 };

/** la barre est redessinée pour l'espace `ctx` (null : l'accueil du hub) @param {string | null} ctx */
export function barFor(ctx) {
  if (ctx === barOf) return;
  barOf = ctx;
  swapped = performance.now();
}

/** vrai si ce toucher de la barre est l'écho d'un double toucher @param {MouseEvent} e */
export function echo(e) {
  const same = Math.hypot(e.clientX - last.x, e.clientY - last.y) < 24;
  if (same && performance.now() - swapped < 350) return true;
  last = { x: e.clientX, y: e.clientY };
  return false;
}
