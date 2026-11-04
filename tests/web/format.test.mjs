// Modules de l'app sans navigateur (chantier S13) : node --test tests/web/
import assert from "node:assert/strict";
import { test } from "node:test";

import { chf, chf2, date, decimals, initials, locale, monthName, pct, setBase, setLocale, signed, spct, toMinor, units } from "../../hub/web/format.js";

test("le séparateur des milliers vient de la locale du profil", () => {
  assert.equal(locale(), "fr");
  assert.equal(chf(1234567), "1\u202f234\u202f567");
  assert.equal(setLocale("fr-CH"), true);
  assert.equal(setLocale("fr-CH"), false);
  assert.equal(chf(1234567), "1'234'567"); // l'apostrophe droite, jamais la typographique
  assert.equal(setLocale(null), false);
});

test("montants avec l'apostrophe des milliers (fr-CH), vrai signe moins", () => {
  setLocale("fr-CH");
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

test("montants par l'exposant de la devise de base, jamais par 100 en dur", () => {
  assert.equal(units({ minor: 123456, currency: "CHF" }), 1234.56);
  assert.equal(toMinor("12.345"), 1235);
  assert.equal(units(null), null);
  assert.equal(setBase("JPY", 0), true);
  assert.equal(decimals(), 0);
  assert.equal(units({ minor: 1234, currency: "JPY" }), 1234);
  assert.equal(toMinor(99.6), 100);
  assert.equal(chf2(-1234), "−1'234");
  assert.equal(setBase("CHF", 2), true);
  assert.equal(setBase("CHF", 2), false);
  assert.equal(chf2(-1234.5), "−1'234.50");
});
