// @ts-check
// Ce que le Face ID de « À valider » signe (audit du 10/11, W1) : seulement ce qui est affiché et
// coché. Une carte proposée par un assistant, ou qui a changé depuis sa dernière lecture, n'est
// jamais cochée d'avance : c'est toi qui la coches, après l'avoir lue.

/** @typedef {{ id: string, revision: number, created_by: string }} Card */

const key = (/** @type {Card} */ p) => `${p.id}:${p.revision}`; // une carte qui change perd sa coche

/** à relire avant de signer : jamais cochée d'avance
 * @param {Card} p */
export const careful = (p) => p.created_by.startsWith("token:") || p.revision > 1;

/** @param {Card} p @param {Map<string, boolean>} choices */
export const ticked = (p, choices) => choices.get(key(p)) ?? !careful(p);

/** @param {Card} p @param {Map<string, boolean>} choices @param {boolean} on */
export function tick(p, choices, on) {
  choices.set(key(p), on);
}

/** les propositions que le bouton signe : cochées, parmi les `shown` premières (celles à l'écran)
 * @param {Card[]} list @param {Map<string, boolean>} choices @param {number} [shown] */
export function chosen(list, choices, shown = list.length) {
  return list.slice(0, shown).filter((p) => ticked(p, choices)).map((p) => p.id);
}
