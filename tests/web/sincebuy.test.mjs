// Le gain d'une ligne : depuis l'achat, sur le prix de revient (16/11 : +172 % affichés pour un
// gain de 1 438 sur 7 666, le % d'une période rapporté à un capital moyen minuscule).
import assert from "node:assert/strict";
import { test } from "node:test";
import { sinceBuy } from "../../hub/domains/finance/web/wcurve.js";

test("le gain et le % se lisent sur le prix de revient", () => {
  const r = sinceBuy(7666, 6228);
  assert.equal(r.gain, 1438);
  assert.ok(Math.abs(r.pct - 0.2309) < 1e-3);
});

test("un gain déjà calculé (crypto, parts dont l'achat est connu) garde sa base", () => {
  assert.deepEqual(sinceBuy(null, 1000, -100), { gain: -100, pct: -0.1 });
});

test("sans prix de revient connu et positif : rien plutôt qu'un chiffre faux", () => {
  assert.equal(sinceBuy(500, null), null);
  assert.equal(sinceBuy(500, 0), null);
  assert.equal(sinceBuy(500, -3), null);
});
