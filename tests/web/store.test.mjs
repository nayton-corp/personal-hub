// Mois budgétaire côté app : même règle que period.py côté serveur (jour de début après le 15 :
// le mois porte le nom de sa fin).
import assert from "node:assert/strict";
import { test } from "node:test";

import { currentMonth, monthSpan, shiftMonth } from "../../hub/web/store.js";

test("décaler un mois franchit les années", () => {
  assert.equal(shiftMonth("2026-01", -1), "2025-12");
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
  assert.equal(shiftMonth("2026-03", -15), "2024-12");
});

test("mois budgétaire selon le jour de début, dans le fuseau de l'instance", () => {
  const at = new Date("2026-10-24T22:30:00Z"); // 25 octobre à Zurich
  assert.equal(currentMonth(at, 1), "2026-10");
  assert.equal(currentMonth(at, 25), "2026-11");
  assert.equal(currentMonth(at, 26), "2026-10");
  assert.equal(currentMonth(new Date("2026-10-03T10:00:00Z"), 5), "2026-09");
});

test("bornes d'un mois budgétaire, dates comprises", () => {
  assert.deepEqual(monthSpan("2026-02", 1), ["2026-02-01", "2026-02-28"]);
  assert.deepEqual(monthSpan("2026-11", 25), ["2026-10-25", "2026-11-24"]);
  assert.deepEqual(monthSpan("2026-03", 10), ["2026-03-10", "2026-04-09"]);
});
