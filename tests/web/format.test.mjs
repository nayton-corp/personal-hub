// Modules de l'app sans navigateur (chantier S13) : node --test tests/web/
import assert from "node:assert/strict";
import { test } from "node:test";

import { chf, chf2, date, initials, monthName, pct, signed, spct } from "../../hub/web/format.js";

test("montants à la suisse : apostrophe des milliers, vrai signe moins", () => {
  assert.equal(chf(1234567.4), "1'234'567");
  assert.equal(chf(-1234.5), "−1'235");
  assert.equal(chf(-0.4), "0");
  assert.equal(chf(null), "—");
  assert.equal(chf2(-1234.5), "−1'234.50");
  assert.equal(signed(12), "+12");
  assert.equal(signed(-12), "−12");
});

test("pourcentages avec virgule décimale", () => {
  assert.equal(pct(0.1234, 1), "12,3 %");
  assert.equal(spct(-0.05), "−5,0 %");
  assert.equal(pct(Number.NaN), "—");
});

test("dates sans dépendre du fuseau de la machine", () => {
  assert.equal(date("2026-01-05"), "5 janv. 2026");
  assert.equal(date("2026-12-31T23:30:00Z"), "31 déc. 2026");
  assert.equal(monthName("2026-08"), "août 2026");
  assert.equal(initials("Banque cantonale · épargne"), "BC");
});
