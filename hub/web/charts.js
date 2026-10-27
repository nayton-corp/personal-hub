// Graphiques d3 repris du prototype (L2-03). d3 v7 est servi par le hub (vendor/), jamais par
// un CDN : la CSP n'autorise que script-src 'self'. Les couleurs passent par style() (CSSOM),
// qu'autorise style-src 'self', et jamais par un attribut style.
import { MOIS, MOIS_L, chf, date, el, pct } from "./format.js";

const d3 = () => window.d3;

export const COLORS = {
  acc: "var(--acc)", fixed: "var(--chart-muted)", variable: "var(--acc)", savings: "var(--ok)",
  grid: "var(--grid)", muted: "var(--muted)", ref: "var(--reference)",
};

export function clear(box) {
  box.querySelectorAll("svg, .empty").forEach((n) => n.remove());
  const tip = box.querySelector(".tip");
  if (tip) tip.style.display = "none";
}

export function placeholder(box, text) {
  clear(box);
  box.insertBefore(el("div", "empty center", text), box.firstChild);
}

function tipAt(box, tip, px, py, lines) {
  tip.replaceChildren(...lines.map((l, i) => el("div", i === 0 ? "muted" : "", l)));
  tip.style.display = "block";
  tip.style.left = `${Math.max(0, Math.min(px + 12, box.clientWidth - tip.offsetWidth - 4))}px`;
  tip.style.top = `${Math.max(0, py - 44)}px`;
}

function svgIn(box, W, H) {
  return d3().select(box).insert("svg", ".tip").attr("width", "100%").attr("viewBox", `0 0 ${W} ${H}`);
}

function muted(sel) {
  return sel.attr("font-size", 10).style("fill", COLORS.muted);
}

// courbe du patrimoine : rows = [{date: Date, v, ref?}]
export function area(box, rows, opts) {
  clear(box);
  if (!rows) return;
  if (rows.length < 2) {
    placeholder(box, "Courbe en construction : un point par fin de mois, à partir des relevés importés.");
    return;
  }
  if (!box.clientWidth || !d3()) return;
  const D = d3();
  const tip = box.querySelector(".tip");
  const W = box.clientWidth, H = opts.h, m = { top: 10, right: 8, bottom: 22, left: 6 };
  const svg = svgIn(box, W, H);
  const vals = rows.flatMap((r) => (r.ref == null ? [r.v] : [r.v, r.ref]));
  const lo = D.min(vals), hi = D.max(vals), pad = Math.max(1, (hi - lo) * 0.08);
  const y = D.scaleLinear([lo - pad, hi + pad], [H - m.bottom, m.top]);
  const x = D.scaleUtc(D.extent(rows, (r) => r.date), [m.left, W - m.right]);
  svg.append("g").selectAll("line").data(y.ticks(3)).join("line")
    .attr("x1", m.left).attr("x2", W - m.right).attr("y1", y).attr("y2", y).style("stroke", COLORS.grid);
  muted(svg.append("g").selectAll("text").data(y.ticks(3)).join("text")
    .attr("x", m.left).attr("y", (t) => y(t) - 4)).text((t) => opts.fmt(t));
  const every = Math.max(1, Math.round(rows.length / 4));
  const ticks = rows.filter((r, i) => i % every === 0 || i === rows.length - 1);
  muted(svg.append("g").selectAll("text").data(ticks).join("text")
    .attr("x", (r) => x(r.date)).attr("y", H - 6)
    .attr("text-anchor", (r, i, a) => (i === 0 ? "start" : i === a.length - 1 ? "end" : "middle")))
    .text((r) => MOIS[r.date.getUTCMonth()] + (opts.year ? ` ${String(r.date.getUTCFullYear()).slice(2)}` : ""));
  const gid = `g${Math.round(Math.random() * 1e6)}`;
  const grad = svg.append("defs").append("linearGradient").attr("id", gid)
    .attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
  [[0, 0.28], [0.3, 0.14], [0.6, 0.05], [1, 0]].forEach(([o, a]) =>
    grad.append("stop").attr("offset", o).attr("stop-opacity", a).style("stop-color", COLORS.acc));
  svg.append("path").datum(rows)
    .attr("d", D.area().x((r) => x(r.date)).y0(H - m.bottom).y1((r) => y(r.v)))
    .attr("fill", `url(#${gid})`);
  if (rows.some((r) => r.ref != null)) {
    svg.append("path").datum(rows).attr("d", D.line().x((r) => x(r.date)).y((r) => y(r.ref)))
      .attr("fill", "none").attr("stroke-width", 1.25).attr("stroke-dasharray", "3 4").style("stroke", COLORS.ref);
  }
  svg.append("path").datum(rows).attr("d", D.line().x((r) => x(r.date)).y((r) => y(r.v)))
    .attr("fill", "none").attr("stroke-width", 2.25).attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round").style("stroke", COLORS.acc);
  const last = rows[rows.length - 1];
  svg.append("circle").attr("cx", x(last.date)).attr("cy", y(last.v)).attr("r", 4).attr("stroke-width", 2)
    .style("fill", COLORS.acc).style("stroke", "var(--panel)");
  const rule = svg.append("line").attr("y1", m.top).attr("y2", H - m.bottom).style("stroke", COLORS.ref).style("display", "none");
  const dot = svg.append("circle").attr("r", 4).style("fill", COLORS.acc).style("display", "none");
  const bis = D.bisector((r) => r.date).center;
  const show = (ev) => {
    const [mx] = D.pointer(ev);
    const r = rows[Math.max(0, Math.min(rows.length - 1, bis(rows, x.invert(mx))))];
    rule.style("display", null).attr("x1", x(r.date)).attr("x2", x(r.date));
    dot.style("display", null).attr("cx", x(r.date)).attr("cy", y(r.v));
    tipAt(box, tip, (x(r.date) / W) * box.clientWidth, y(r.v), [date(r.iso), ...opts.tip(r)]);
  };
  svg.on("mousemove", show).on("touchmove", show).on("mouseleave", () => {
    tip.style.display = "none";
    rule.style("display", "none");
    dot.style("display", "none");
  });
}

// barres horizontales : parts = [{n, v, cls?}]
export function hbars(box, parts, fmt) {
  box.replaceChildren();
  if (!parts) return;
  const shown = parts.filter((p) => p.v > 0);
  if (!shown.length) {
    box.append(el("div", "empty", "Rien à afficher pour l'instant."));
    return;
  }
  const total = shown.reduce((s, p) => s + p.v, 0);
  const max = Math.max(...shown.map((p) => p.v));
  for (const p of shown) {
    const hb = el("div", "hb");
    const l = el("div", "l");
    const v = el("span", "v", pct(p.v / total));
    v.prepend(el("b", "amt", fmt(p.v)));
    l.append(el("span", "", p.n), v);
    const bar = el("div", "bar");
    const i = el("i", p.cls || "");
    i.style.width = `${(p.v / max) * 100}%`;
    bar.append(i);
    hb.append(l, bar);
    box.append(hb);
  }
}

// barres empilées par mois : series = [{month, fixed, variable, savings}]
export function months(box, series) {
  clear(box);
  if (!series) return;
  if (!series.some((s) => s.fixed || s.variable || s.savings)) {
    placeholder(box, "Pas encore de mois avec des écritures.");
    return;
  }
  if (!box.clientWidth || !d3()) return;
  const D = d3();
  const tip = box.querySelector(".tip");
  const keys = ["fixed", "variable", "savings"];
  const label = { fixed: "Fixe", variable: "Variable", savings: "Épargne" };
  const W = box.clientWidth, H = 180, m = { top: 8, right: 4, bottom: 22, left: 4 };
  const svg = svgIn(box, W, H);
  const rows = series.map((s) => ({ month: s.month, fixed: Math.max(0, s.fixed), variable: Math.max(0, s.variable), savings: Math.max(0, s.savings) }));
  const yMax = D.max(rows, (r) => r.fixed + r.variable + r.savings) || 1;
  const x = D.scaleBand(rows.map((r) => r.month), [m.left, W - m.right]).padding(0.45);
  const y = D.scaleLinear([0, yMax], [H - m.bottom, m.top]);
  svg.append("g").selectAll("line").data(y.ticks(3)).join("line")
    .attr("x1", m.left).attr("x2", W - m.right).attr("y1", y).attr("y2", y).style("stroke", COLORS.grid);
  muted(svg.append("g").selectAll("text").data(y.ticks(3)).join("text")
    .attr("x", m.left).attr("y", (t) => y(t) - 3)).text((t) => `${chf(t / 1000)} k`);
  muted(svg.append("g").selectAll("text").data(rows).join("text")
    .attr("x", (r) => x(r.month) + x.bandwidth() / 2).attr("y", H - 6).attr("text-anchor", "middle"))
    .text((r) => MOIS[Number(r.month.slice(5, 7)) - 1]);
  const stacked = D.stack().keys(keys)(rows);
  svg.append("g").selectAll("g").data(stacked).join("g").style("fill", (s) => COLORS[s.key])
    .selectAll("rect").data((s) => s.map((p) => ({ p, key: s.key }))).join("rect")
    .attr("x", (d) => x(d.p.data.month)).attr("y", (d) => y(d.p[1]))
    .attr("height", (d) => Math.max(0, y(d.p[0]) - y(d.p[1]))).attr("width", x.bandwidth()).attr("rx", 4)
    .on("mousemove", (ev, d) => {
      const [px, py] = D.pointer(ev, box);
      tipAt(box, tip, px, py, [MOIS_L[Number(d.p.data.month.slice(5, 7)) - 1], `${label[d.key]} ${chf(d.p[1] - d.p[0])} CHF`]);
    })
    .on("mouseleave", () => { tip.style.display = "none"; });
}

// flux revenus → groupes → catégories : flows = réponse de /api/finance/flows
export function sankey(box, flows) {
  clear(box);
  if (!flows) return;
  const income = flows.income.minor / 100;
  const order = ["fixed", "variable", "savings"];
  const name = { fixed: "Fixe", variable: "Variable", savings: "Épargne" };
  const groups = flows.groups.map((g) => ({ ...g, v: g.total.minor / 100 })).filter((g) => g.v > 0);
  const rest = flows.remainder.minor / 100;
  if (income <= 0 || !groups.length) {
    placeholder(box, "Pas assez de mouvements ce mois pour dessiner le flux.");
    return;
  }
  if (!box.clientWidth || !d3()) return;
  const D = d3();
  const tip = box.querySelector(".tip");
  const W = box.clientWidth, H = 360, nw = 8, gap = 8;
  const col1 = order.map((g) => groups.find((x) => x.group === g)).filter(Boolean)
    .map((g) => ({ n: name[g.group], key: g.group, v: g.v, c: COLORS[g.group] }));
  const col2 = [];
  for (const g of col1) {
    const src = groups.find((x) => x.group === g.key);
    for (const it of src.items) {
      const v = it.total.minor / 100;
      if (v > 0) col2.push({ n: it.name, g: g.key, v, c: g.c });
    }
  }
  if (rest > 0) {
    col1.push({ n: "Reste", key: "rest", v: rest, c: COLORS.savings });
    col2.push({ n: "Sur le compte", g: "rest", v: rest, c: COLORS.savings });
  }
  const total = D.sum(col1, (n) => n.v);
  const col0 = [{ n: "Revenus", v: total, c: COLORS.acc }];
  const labelW = Math.min(140, Math.max(96, W * 0.34));
  const xs = [0, Math.round((W - labelW) * 0.42), W - labelW - nw];
  const k = (H - gap * Math.max(0, col2.length - 1)) / total;
  const place = (col, x) => {
    let y0 = (H - D.sum(col, (n) => n.v * k) - gap * (col.length - 1)) / 2;
    for (const n of col) {
      Object.assign(n, { x, y: y0, h: n.v * k, out: 0, inn: 0 });
      y0 += n.h + gap;
    }
  };
  place(col0, xs[0]);
  place(col1, xs[1]);
  place(col2, xs[2]);
  const svg = svgIn(box, W, H);
  const rib = (a, b, v, c, label) => {
    const h = v * k, y0 = a.y + a.out, y1 = b.y + b.inn, x0 = a.x + nw, x1 = b.x, mx = (x0 + x1) / 2;
    a.out += h;
    b.inn += h;
    svg.append("path")
      .attr("d", `M${x0},${y0} C${mx},${y0} ${mx},${y1} ${x1},${y1} L${x1},${y1 + h} C${mx},${y1 + h} ${mx},${y0 + h} ${x0},${y0 + h} Z`)
      .attr("fill-opacity", 0.25).style("fill", c)
      .on("mousemove", (ev) => {
        const [px, py] = D.pointer(ev, box);
        tipAt(box, tip, px, py, [label, `${chf(v)} CHF · ${pct(v / total)}`]);
      })
      .on("mouseleave", () => { tip.style.display = "none"; });
  };
  for (const g of col1) rib(col0[0], g, g.v, g.c, `Revenus → ${g.n}`);
  for (const n of col2) {
    const src = col1.find((g) => g.key === n.g);
    if (src) rib(src, n, n.v, n.c, `${src.n} → ${n.n}`);
  }
  const nodes = [...col0, ...col1, ...col2];
  svg.append("g").selectAll("rect").data(nodes).join("rect")
    .attr("x", (n) => n.x).attr("y", (n) => n.y).attr("width", nw).attr("height", (n) => Math.max(2, n.h))
    .attr("rx", 3).style("fill", (n) => n.c);
  svg.append("g").selectAll("text").data(nodes).join("text")
    .attr("x", (n) => n.x + nw + 5).attr("y", (n) => n.y + n.h / 2 + 4).attr("font-size", 10)
    .attr("font-weight", (n, i) => (i < col0.length + col1.length ? 600 : 400)).style("fill", "var(--fg)")
    .text((n) => `${n.n} ${chf(n.v)}`);
}
