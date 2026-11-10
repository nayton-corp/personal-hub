// Ce qu'un passage n'a pas lu, en mots : un explorateur fermé (Base) se dit avec sa cause, sur la
// connexion, et ne reste pas en « À faire » sans geste possible (audit du 10/11, X1).
import assert from "node:assert/strict";
import { test } from "node:test";
import { gapNote, gapRows, gapText } from "../../hub/domains/finance/web/gaps.js";

const blocked = { scope: "history.coinbase-wallet.base", reason: "blocked" };
const key = { scope: "history.coinbase-wallet.arbitrum", reason: "key" };

test("un explorateur fermé dit sa cause, sans promettre le prochain passage", () => {
  const text = gapText(blocked);
  assert.match(text, /Historique Base de coinbase-wallet/);
  assert.match(text, /refuse l'accès/);
  assert.match(text, /chaque semaine/);
  assert.doesNotMatch(text, /prochain passage/);
});

test("un réseau en solde seul n'est pas une ligne « À faire »", () => {
  const items = [{ label: "Marché", mode: "enabled", gaps: [blocked] }];
  assert.deepEqual(gapRows({ items }), []);
  assert.match(gapNote(items[0]), /^ · Historique Base/);
});

test("un manque qui a un geste reste sur l'accueil, seul", () => {
  const rows = gapRows({ items: [{ label: "Marché", mode: "enabled", gaps: [blocked, key] }] });
  assert.equal(rows.length, 1);
  assert.match(rows[0].s, /clé Etherscan refusée/);
  assert.doesNotMatch(rows[0].s, /Base/);
});

test("une connexion complète n'ajoute rien à son dernier passage", () => {
  assert.equal(gapNote({ gaps: [] }), "");
  assert.equal(gapNote(undefined), "");
});
