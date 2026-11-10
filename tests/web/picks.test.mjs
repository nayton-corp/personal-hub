// Le Face ID de « À valider » ne signe que ce qui est affiché et coché (audit du 10/11, W1).
import assert from "node:assert/strict";
import { test } from "node:test";
import { careful, chosen, tick, ticked } from "../../hub/web/picks.js";

const card = (id, created_by = "user:moi", revision = 1) => ({ id, created_by, revision });
const five = ["a", "b", "c", "d", "e"].map((id) => card(id));

test("l'accueil ne signe que ses lignes, pas les cartes qu'il ne montre pas", () => {
  assert.deepEqual(chosen(five, new Map(), 3), ["a", "b", "c"]);
  assert.deepEqual(chosen(five, new Map()), ["a", "b", "c", "d", "e"]); // le panneau montre tout
});

test("une carte d'assistant n'est jamais cochée d'avance", () => {
  const list = [card("a"), card("b", "token:brain"), card("c", "system")];
  const choices = new Map();
  assert.equal(careful(list[1]), true);
  assert.deepEqual(chosen(list, choices), ["a", "c"]);
  tick(list[1], choices, true); // cochée à la main, après lecture
  assert.deepEqual(chosen(list, choices), ["a", "b", "c"]);
});

test("une carte qui a changé perd sa coche et se relit", () => {
  const choices = new Map();
  const before = card("a");
  assert.equal(ticked(before, choices), true);
  tick(before, choices, true);
  const after = card("a", "user:moi", 2);
  assert.equal(ticked(after, choices), false);
});

test("une carte décochée reste décochée", () => {
  const choices = new Map();
  tick(five[0], choices, false);
  assert.deepEqual(chosen(five, choices, 3), ["b", "c"]);
});
