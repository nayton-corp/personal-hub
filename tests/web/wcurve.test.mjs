// Le pas de la courbe : chaque jour jusqu'à six mois, chaque dimanche au-delà ; le mot affiché suit
// l'écart le plus courant, pas le premier intervalle, plus court (audit du 10/11, G1).
import assert from "node:assert/strict";
import { test } from "node:test";
import { granLabel, stepFor } from "../../hub/domains/finance/web/wcurve.js";

const pts = (...ds) => ds.map((d) => ({ d }));

test("six mois par jour, un an par semaine", () => {
  assert.equal(stepFor("2026-05-12", "2026-11-10"), "day");
  assert.equal(stepFor("2025-11-10", "2026-11-10"), "week");
  assert.equal(stepFor(null, "2026-11-10"), "day");
});

test("le mot suit l'écart le plus courant", () => {
  assert.equal(granLabel(pts("2026-01-01", "2026-01-02", "2026-01-03")), "par jour");
  // un jeudi, puis les dimanches, puis un mardi : deux intervalles courts aux bords
  assert.equal(granLabel(pts("2026-01-01", "2026-01-04", "2026-01-11", "2026-01-18", "2026-01-25", "2026-01-27")), "par semaine");
  assert.equal(granLabel(pts("2026-01-10", "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-04")), "par mois");
  assert.equal(granLabel(pts("2026-01-01")), "");
});
