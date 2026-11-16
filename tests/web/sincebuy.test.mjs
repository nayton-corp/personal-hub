// Le gain d'une ligne : depuis l'achat, sur le prix de revient (et non plus le % d'une période
// rapporté à un capital moyen qui peut être minuscule).
import assert from "node:assert/strict";
import { test } from "node:test";
import { sinceBuy } from "../../hub/domains/finance/web/wcurve.js";

test("le gain et le % se lisent sur le prix de revient", () => {
  const r = sinceBuy(1200, 1000);
  assert.equal(r.gain, 200);
  assert.ok(Math.abs(r.pct - 0.2) < 1e-9);
});

test("un gain déjà calculé (crypto, parts dont l'achat est connu) garde sa base", () => {
  assert.deepEqual(sinceBuy(null, 1000, -100), { gain: -100, pct: -0.1 });
});

test("sans prix de revient connu et positif : rien plutôt qu'un chiffre faux", () => {
  assert.equal(sinceBuy(500, null), null);
  assert.equal(sinceBuy(500, 0), null);
  assert.equal(sinceBuy(500, -3), null);
});
