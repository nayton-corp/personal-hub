// La sélection demandée à /finance/performance : un compte choisi en entier garde ses positions
// vendues (audit du 10/11 : le rendement d'une vue avec crédit, Brut ou filtrée les oubliait).
import assert from "node:assert/strict";
import { test } from "node:test";
import { moneyRate, perfSel } from "../../hub/domains/finance/web/wcurve.js";

const pos = (acc, isin) => ({ acc, kind: "securities", asset: `isin:${isin}` });
const cash = (acc) => ({ acc, kind: "cash", asset: "ccy:CHF" });
const debt = { acc: "debt:D1", kind: "debt", asset: "debt:D1" };
const every = [cash("bank"), pos("ibkr", "F1"), pos("ibkr", "F2"), cash("ibkr"), pos("ledger", "BTC"), debt];

test("un compte dont toutes les lignes sont choisies est demandé en entier", () => {
  const owned = every.filter((l) => l.kind !== "debt");
  assert.equal(perfSel(owned, every), "&account=bank&account=ibkr&account=ledger");
  assert.equal(perfSel(every, every), "&account=bank&account=ibkr&account=ledger&line=debt%3AD1");
});

test("un compte choisi en partie : ses lignes nommées, et son solde pour les revenus et frais", () => {
  const sel = [every[1], every[4]];
  assert.equal(perfSel(sel, every), "&account=ledger&line=ibkr%7CF1&line=ibkr%7Ccash");
});

test("un actif choisi ne s'élargit jamais au compte", () => {
  assert.equal(perfSel([every[4]], every, true), "&line=ledger%7CBTC&line=ledger%7Ccash");
});

// Le pourcentage à côté des francs : le rendement de l'argent engagé, par an passé un an.
test("jusqu'à un an le rendement de la période, au-delà le taux annuel exact", () => {
  assert.deepEqual(moneyRate(-0.074, 182), { v: -0.074, yr: false });
  assert.deepEqual(moneyRate(-0.074, 365, -0.077), { v: -0.074, yr: false }); // un an : la période
  assert.deepEqual(moneyRate(0.3, 3970, 0.023), { v: 0.023, yr: true });
});

test("rien plutôt qu'un taux approché", () => {
  assert.equal(moneyRate(null, 30), null); // pas de capital engagé
  assert.equal(moneyRate(0.21, 730), null); // plus d'un an sans taux exact : les francs seuls
});
