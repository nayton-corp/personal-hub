// Patrimoine : les panneaux. Filtres (les quatre critères d'avant, plus Compte et Actif), périodes
// (dix au choix, six épinglées, une plage libre), « Répartir par » (ce qui filtre, puis ce qui se
// lit dans les fonds), « Voir le patrimoine de… » (passer d'un compte à l'autre), le repère de
// la performance en %, et les actifs d'un bloc du contenu des fonds.
import { BY, FILTERS, LOOK, PRESETS, S, accLabel, asOf, fMark, fName, firstDay, here, lines, match, sum } from "./wstate.js";
import { SHEETS, amount, esc, ic, share } from "../../ui.js";
import { FACET, assetMark, facetMark, instMark } from "./meta.js";
import { KIND_LABEL } from "./wstate.js";
import { units } from "./perf.js";
import { store } from "../../store.js";

const BY_HINT = {
  cat: "Liquidités, actions et fonds, crypto", liq: "Immédiate, quelques jours, bloquée", goal: "Courant, projets, long terme, retraite",
  inst: "Chaque banque ou plateforme", acc: "Chaque compte", asset: "Chaque titre, fonds, crypto ou devise",
  region: "Où sont les entreprises de tes fonds", sector: "Dans quels secteurs ils investissent", currency: "Exposition par devise, liquidités comprises",
};
export const byLabel = (k) => (FACET[k] ? FACET[k].label : k === "acc" ? "Compte" : k === "asset" ? "Actif" : LOOK.find(([x]) => x === k)[1]);

SHEETS.filters = () => {
  const all = lines() || [];
  const n = FILTERS.reduce((t, f) => t + S.filters[f.key].size, 0);
  return {
    title: "Filtres",
    act: n ? '<button class="clear-link" type="button" data-a="w-clear">Tout effacer</button>' : "",
    body: `<p class="hint">Plusieurs choix dans un critère s'additionnent ; deux critères se combinent.</p>${FILTERS.map((f) => {
      const k = S.filters[f.key].size;
      const vals = f.key === "acc" || f.key === "asset"
        ? f.values.slice().sort((a, b) => sum(all.filter((l) => l[f.key] === b)) - sum(all.filter((l) => l[f.key] === a)))
        : f.values;
      return `<div class="facet" role="group" aria-label="${f.label}"><div class="facet-head">${f.label}<span>${k ? `${k} choisi${k > 1 ? "s" : ""}` : "Tous"}</span></div><div class="opts">${vals.map((v) => {
        const val = sum(all.filter((l) => l[f.key] === v && match(l, f.key))), on = S.filters[f.key].has(v);
        return `<button class="opt" type="button" data-a="w-opt" data-v="${f.key}|${esc(v)}" aria-pressed="${on}" ${Math.abs(val) < 0.5 && !on ? "disabled" : ""}>${fMark(f.key, v, "xs")}<span><b>${esc(fName(f.key, v))}</b><span>${Math.abs(val) >= 0.5 ? amount(val) : "aucun avoir"}</span></span></button>`;
      }).join("")}</div></div>`;
    }).join("")}`,
    foot: `<button class="primary num" type="button" data-a="sheet-close" data-autofocus>Afficher ${amount(sum(all.filter((l) => match(l) && !(S.gross && l.kind === "debt"))))}</button>`,
  };
};

SHEETS.periods = () => {
  const first = firstDay() || asOf(), last = asOf();
  const c = S.custom || [null, null];
  const d0 = c[0] || (() => {
    const d = new Date(`${last}T00:00:00Z`);
    d.setUTCMonth(d.getUTCMonth() - 6);
    const s = d.toISOString().slice(0, 10);
    return s < first ? first : s;
  })();
  return {
    title: "Période",
    body: `<p class="hint">Touche une période pour l'afficher. L'épingle la met dans la barre sous la courbe (de 2 à 6).</p>
      <div class="list">${PRESETS.map((p) => {
        const on = !S.custom && S.period === p.k, pinned = S.pinned.includes(p.k);
        return `<div class="prow"><button class="prow-main" type="button" data-a="w-period" data-v="${p.k}" aria-pressed="${on}"><b>${p.k}</b><span>${esc(p.label)}</span>${on ? ic("check") : ""}</button>
          <button class="pin" type="button" data-a="w-pin" data-v="${p.k}" aria-pressed="${pinned}" aria-label="${pinned ? "Retirer de" : "Ajouter à"} la barre : ${esc(p.label)}">${ic("pin")}</button></div>`;
      }).join("")}</div>
      <h3>Plage personnalisée</h3>
      <div class="jf-pair"><label class="field" for="w-d0">Du<input type="date" id="w-d0" value="${d0}" min="${first}" max="${last}"></label>
      <label class="field" for="w-d1">Au<input type="date" id="w-d1" value="${c[1] || last}" min="${first}" max="${last}"></label></div>`,
    foot: '<button class="primary" type="button" data-a="w-custom">Afficher cette plage</button>',
  };
};

SHEETS.by = () => {
  const opt = (k) => `<button class="row byrow" type="button" data-a="w-by" data-v="${k}" aria-pressed="${S.by === k}"><span class="row-main"><span class="row-title">${esc(byLabel(k))}</span><span class="row-sub">${BY_HINT[k]}</span></span><span class="chk">${S.by === k ? ic("check") : ""}</span></button>`;
  return {
    title: "Répartir par",
    body: `<h3 class="grp-title">Selon tes comptes · toucher un bloc filtre l'écran</h3><div class="list">${BY.map(opt).join("")}</div>
      <h3 class="grp-title">Dans tes fonds · lecture seule</h3><div class="list">${LOOK.map(([k]) => opt(k)).join("")}</div>`,
  };
};

// « Voir le patrimoine de… » : tout, ou un compte, rangés par nature
SHEETS.switch = () => {
  const all = lines() || [];
  const cur = here();
  const row = (on, mark, t, sub, v, a, val) => `<button class="row go-row" type="button" data-a="${a}" data-v="${esc(val)}" aria-current="${on}">${mark}<span class="row-main"><span class="row-title">${esc(t)}</span><span class="row-sub">${esc(sub)}</span></span><span class="row-num"><span class="row-val num">${amount(v)}</span></span><span class="go">${on ? ic("check") : ""}</span></button>`;
  let body = row(cur.t === "home", `<span class="ibox tint sm" data-css="--c:var(--accent)" aria-hidden="true">${ic("layers")}</span>`, "Tout le patrimoine", "net, tous les comptes", sum(all), "w-home", "");
  const accs = new Map();
  for (const l of all) accs.set(l.acc, [...(accs.get(l.acc) || []), l]);
  for (const kind of ["cash", "securities", "pension", "crypto", "debt"]) {
    const group = [...accs.values()].filter((ls) => ls[0].kind === kind).sort((a, b) => sum(b) - sum(a));
    if (!group.length) continue;
    body += `<h3 class="grp-title">${KIND_LABEL[kind] === "Compte" ? "Comptes" : kind === "debt" ? "Dettes" : KIND_LABEL[kind]}</h3>`;
    body += group.map((ls) => row(cur.t === "acc" && cur.id === ls[0].acc, kind === "debt" ? facetMark("cat", "debt") : instMark(ls[0].inst), accLabel(ls[0]), kind === "debt" ? "dette" : FACET.goal.names[ls[0].goal] || "", sum(ls), "w-switch-acc", ls[0].acc)).join("");
  }
  return { title: "Voir le patrimoine de…", body };
};

// repère de la performance en % : un fonds que tu détiens (son cours), ou aucun
SHEETS.cmp = () => {
  const funds = new Map();
  for (const l of lines() || []) if (l.isin && l.cat !== "crypto" && l.price) funds.set(l.isin, l);
  const opt = (v, t, sub, mark) => `<button class="row byrow" type="button" data-a="w-cmp-set" data-v="${esc(v)}" aria-pressed="${S.cmp === (v || null)}">${mark}<span class="row-main"><span class="row-title">${esc(t)}</span><span class="row-sub">${esc(sub)}</span></span><span class="chk">${S.cmp === (v || null) ? ic("check") : ""}</span></button>`;
  return {
    title: "Repère",
    body: `<p class="hint">La courbe en % se compare au cours d'un fonds, ramené à 0 au début de la période. Un fonds indiciel (MSCI World, SPI) sert d'indice.</p>
      <div class="list">${opt("", "Aucun repère", "la performance seule", `<span class="ibox tint sm" data-css="--c:var(--muted)" aria-hidden="true">${ic("close")}</span>`)}
      ${[...funds.values()].map((l) => opt(l.isin, l.name, l.isin, assetMark(l, "sm"))).join("")}</div>
      <p class="hint">L'inflation suisse viendra avec une source de prix à la consommation (OFS) : elle n'est pas encore lue par le hub.</p>`,
  };
};

// actifs d'un bloc du contenu des fonds
SHEETS.bucket = (k) => {
  const e = store.data(`/finance/lookthrough?dimension=${S.by}`);
  const x = e ? e.items.find((it) => it.bucket === k) : null;
  if (!x) return null;
  const all = lines() || [];
  return {
    title: esc(k),
    body: `<div class="sheet-big num">${share(Number(x.weight || 0))} <small>· ${amount(units(x.value))}</small></div>
      <p class="hint">Un fonds est réparti sur plusieurs blocs : ces actifs y contribuent pour une part, sans filtre sur l'écran.</p>
      <div class="list">${(x.assets || []).map((a) => {
        const l = all.find((y) => y.asset === `isin:${a.isin}`);
        return `<button class="sub-row" type="button" data-a="w-open" data-v="${esc(`s:isin:${a.isin}`)}">${l ? assetMark(l, "sm") : facetMark("cat", "funds")}
          <span class="row-main"><span class="row-title">${esc(a.name)}</span><span class="row-sub">${share(units(a.value) / (units(x.value) || 1))} du bloc</span></span>
          <span class="row-num"><span class="num sub-val">${amount(units(a.value))}</span></span><span class="go">${ic("chev")}</span></button>`;
      }).join("")}</div>`,
  };
};
