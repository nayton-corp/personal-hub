// Stratégies : la phrase écrite pendant le réglage est celle que le serveur écrira, les seuils
// restent larges, et une modification n'envoie que ce qui a changé.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as M from "../../hub/domains/finance/web/smodel.js";

const money = (m) => `${(m / 100).toFixed(2)} CHF`;

test("la phrase de chaque genre", () => {
  const tiers = [{ at_pct: 150, sell_pct: 50 }, { at_pct: 100, sell_pct: 25 }];
  assert.equal(M.phrase("ladder", "Altcoins", { tiers }, money), "Quand Altcoins revient à son prix d'achat, j'en vends 25 % ; à +50 %, 50 %.");
  assert.equal(M.phrase("ladder", "Altcoins", { tiers: [{ at_pct: 120, sell_pct: 30 }] }, money), "Quand Altcoins dépasse son prix d'achat de 20 %, j'en vends 30 %.");
  const dca = { cadence: "monthly", day: 5, amount_minor: 20000 };
  assert.equal(M.phrase("recurring", "Bitcoin", dca, money), "Le 5 du mois, j'achète pour 200.00 CHF de Bitcoin.");
  assert.equal(M.phrase("recurring", "Bitcoin", { ...dca, cadence: "weekly", day: 0 }, money), "Chaque lundi, j'achète pour 200.00 CHF de Bitcoin.");
  const dip = { drop_pct: 20, window_days: 90, amount_minor: 50000 };
  assert.equal(M.phrase("dip", "Bitcoin", dip, money), "Si Bitcoin baisse de 20 % depuis son plus haut des 3 derniers mois, j'en achète pour 500.00 CHF.");
  assert.equal(M.phrase("dip", "Bitcoin", { ...dip, amount_minor: 0 }, money), "");
});

test("le 1er du mois, un montant rond sans centimes, un versement sur un compte", () => {
  const n0 = (v) => String(Math.round(v)), n2 = (v) => v.toFixed(2);
  const round = (m) => M.roundMoney(m, 2, "CHF", n0, n2);
  assert.equal(round(20000), "200 CHF");
  assert.equal(round(21250), "212.50 CHF");
  const dca = { cadence: "monthly", day: 1, amount_minor: 20000 };
  assert.equal(M.phrase("recurring", "Bitcoin", dca, round), "Le 1er du mois, j'achète pour 200 CHF de Bitcoin.");
  assert.equal(M.phrase("recurring", "3a VIAC", { ...dca, day: 25, amount_minor: 60000 }, round, true), "Le 25 du mois, je verse 600 CHF sur 3a VIAC.");
  assert.ok(M.isAccount("account:01ABC"));
  assert.ok(!M.isAccount("CRYPTO:BTC"));
  assert.ok(M.isDetected({ origin: "detected" }));
});

test("des seuils larges : pas de petite baisse, pas de paliers serrés", () => {
  assert.ok(Math.min(...M.DROPS) >= 15);
  assert.equal(M.tiersProblem([{ at_pct: 100 }, { at_pct: 105 }]), "Au moins 10 points entre deux paliers");
  assert.equal(M.tiersProblem([{ at_pct: 100 }, { at_pct: 110 }]), null);
  assert.match(M.tiersProblem([]), /Entre 1 et 4/);
  for (const t of M.TEMPLATES) assert.equal(M.tiersProblem(t.tiers.map(([at_pct]) => ({ at_pct }))), null);
});

test("création : tout ; modification : seulement ce qui change", () => {
  const t = M.initial("recurring", null);
  assert.throws(() => M.saveParams({ ...t, scope: "CRYPTO:BTC" }, null), /Montant requis/);
  assert.throws(() => M.saveParams({ ...t, amount: "200" }, null), /sur quoi/);
  const made = M.saveParams({ ...t, scope: "CRYPTO:BTC", amount: "1'250,50", note: " puis rien " }, null);
  assert.deepEqual(made, { kind: "recurring", scope: "CRYPTO:BTC", cadence: "monthly", day: 1, amount_minor: 125050, note: "puis rien" });
  const s = { id: "s1", kind: "recurring", scope: "CRYPTO:BTC", note: null, params: { cadence: "monthly", day: 1, amount_minor: 125050 } };
  const form = M.initial("recurring", s);
  assert.equal(form.amount, "1250.5");
  assert.throws(() => M.saveParams(form, s), /Aucun changement/);
  assert.deepEqual(M.saveParams({ ...form, day: "5" }, s), { strategy_id: "s1", day: 5 });
  assert.deepEqual(M.saveParams({ ...form, note: "ensuite" }, s), { strategy_id: "s1", note: "ensuite" });
});

test("où en est une stratégie, en une ligne", () => {
  const ladder = { kind: "ladder", status: "active", state: "active", level: { ratio_pct: "90.4", next_at_pct: 100 }, kept: { done: 1, skipped: 2 } };
  assert.equal(M.levelLine(ladder), "Aujourd'hui 90 % du prix d'achat · prochain palier au prix d'achat");
  assert.equal(M.levelLine({ ...ladder, level: { ratio_pct: null } }), "Prix d'achat inconnu : rien à comparer pour l'instant");
  assert.equal(M.levelLine({ kind: "dip", status: "active", level: { drop_pct: "22.5", peak_on: "2026-10-01" } }), "Aujourd'hui −22,5 % sous le plus haut du 01.10.2026");
  assert.equal(M.keptLine(ladder), "1 étape tenue · 2 étapes passées");
  const reached = { ...ladder, state: "reached", step: { state: "open", planned: { minor: 52500 }, detail: { at_pct: 100, sell_pct: 25 } } };
  assert.equal(M.stepLine(reached, money), "Palier au prix d'achat atteint : vendre 25 %, environ 525.00 CHF");
  assert.deepEqual(M.stateOf(reached), { label: "Étape atteinte", tone: "info" });
  assert.deepEqual(M.stateOf({ ...reached, step: { state: "later" } }), { label: "Plus tard", tone: "plain" });
});
