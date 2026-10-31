// L'orbe de l'assistant : la même que celle de Domia (frontend/src/ui/orb), en WebGL, sans
// dépendance. Bleue au repos, turquoise à l'écoute, violette quand elle réfléchit, orangée quand
// elle parle, grise quand l'assistant ne répond pas. Elle se fige quand l'app passe en
// arrière-plan, et ne bouge plus quand le système demande moins de mouvement.
import { HALO_FRAGMENT, LINE_FRAGMENT, ORB_FRAGMENT, ORB_VERTEX, QUAD_VERTEX } from "./orb-shaders.js";

/** Repos bleu, écoute turquoise, réflexion violette, parole orangée (les teintes de Cornélius) ; hors service, gris. */
const PALETTES = {
  idle: { hue: 218, accent: 245, energy: 0.38, vivid: 0.36 },
  listening: { hue: 174, accent: 188, energy: 0.96, vivid: 1 },
  thinking: { hue: 285, accent: 318, energy: 0.82, vivid: 0.85 },
  speaking: { hue: 28, accent: 8, energy: 1, vivid: 1 },
  offline: { hue: 218, accent: 245, energy: 0.17, vivid: 0.2 },
};

/** Durée du saut ; au repos, il revient toutes les 9 à 15 s. */
const HOP_MS = 1100;
const HOP_EVERY_MS = 9000;
const HOP_SPREAD_MS = 6000;


/** La pose du saut à l'instant `u` (0 à 1) ; hors de [0, 1), la pose de repos. */
function hop(u) {
  const r = { lift: 0, twist: 0, flow: 0, sx: 1, sy: 1 };
  if (!(u >= 0 && u < 1)) return r;
  if (u < 0.14) {
    const c = Math.sin((u / 0.14) * Math.PI);
    return { ...r, sx: 1 + c * 0.18, sy: 1 - c * 0.15, lift: c * 8 };
  }
  if (u < 0.68) {
    const f = (u - 0.14) / 0.54;
    const wave = Math.sin(f * Math.PI * 2);
    return { lift: -Math.sin(f * Math.PI) * 42, twist: Math.sin(Math.PI * f) ** 2, flow: Math.PI * 2 * f, sx: 1 - wave * 0.1, sy: 1 + wave * 0.12 };
  }
  const l = (u - 0.68) / 0.32;
  const w = Math.sin(l * Math.PI * 3) * (1 - l);
  return { lift: w * 8, twist: Math.sin(l * Math.PI * 2) * (1 - l) * 0.2, flow: 0, sx: 1 + w * 0.19, sy: 1 - w * 0.16 };
}

/** De `from` à `to` par le plus court chemin du cercle des teintes. */
function hueMix(from, to, amount) {
  return from + (((((to - from) % 360) + 540) % 360) - 180) * amount;
}

/** Une couleur TSL (teinte en degrés) en RVB linéaire, ce que le shader attend. */
function hslToLinear(h, s, l) {
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return [lin(f(0)), lin(f(8)), lin(f(4))];
}


function startState(now, mood, reduced) {
  const p = PALETTES[mood];
  // au réveil, l'orbe se déplie d'un point, puis salue
  return { born: now, previous: now, ...p, awake: reduced ? 1 : 0, listening: 0, thinking: 0, speaking: 0, offline: Number(mood === "offline"), deformation: 0, envelope: 0, level: 0, nextHop: now + 420 };
}

/** Ce que le dessin reçoit pour une image : des positions en unités du canevas (il fait 3,2 rayons d'orbe de côté). */

/**
 * Avance l'état jusqu'à `now` et rend l'image. `mic` : le niveau réel du micro (0 à 1) pendant l'écoute, sinon null
 * (simulé quand l'orbe écoute sans micro, comme dans la maquette). `random` : pour l'écart entre deux sauts.
 */
function advance(s, now, mood, reduced, mic = null, random = Math.random) {
  const target = PALETTES[mood];
  const delta = Math.max(0, Math.min(64, now - s.previous));
  s.previous = now;
  const blend = reduced ? 1 : 1 - Math.exp(-delta / 200);
  s.awake += (1 - s.awake) * (reduced ? 1 : 1 - Math.exp(-delta / 260));
  s.hue = hueMix(s.hue, target.hue, blend);
  s.accent = hueMix(s.accent, target.accent, blend);
  s.energy += (target.energy - s.energy) * blend;
  s.vivid += (target.vivid - s.vivid) * blend;
  s.listening += (Number(mood === "listening") - s.listening) * blend;
  s.thinking += (Number(mood === "thinking") - s.thinking) * blend;
  s.speaking += (Number(mood === "speaking") - s.speaking) * blend;
  s.offline += (Number(mood === "offline") - s.offline) * blend;

  const time = reduced ? 0 : (now - s.born) / 1000;
  const syllable = reduced ? 0.35 : ((Math.sin(time * 9.2) + 1) / 2) ** 2 * (0.45 + 0.55 * Math.sin(time * 3.7 + 0.4) ** 2);
  const speech = s.speaking * syllable;
  // la voix colore vite et lisse la forme : l'enveloppe monte en 70 ms, retombe en 240
  s.envelope += (speech - s.envelope) * (1 - Math.exp(-delta / (speech > s.envelope ? 70 : 240)));

  // au repos, un salut de temps en temps ; jamais pendant l'écoute, la réflexion ou la parole
  if (mood !== "idle") s.nextHop = Math.max(s.nextHop, now + 2500);
  let u = (now - s.nextHop) / HOP_MS;
  if (u >= 1) {
    s.nextHop = now + HOP_EVERY_MS + random() * HOP_SPREAD_MS;
    u = -1;
  }
  const pose = reduced ? hop(-1) : hop(u);

  const listening = mood === "listening";
  const heard = mic ?? (listening ? 0.25 + syllable * 0.5 : 0);
  const wanted = listening ? Math.max(0, Math.min(1, (heard - 0.025) * 2.5)) : 0;
  s.level += (wanted - s.level) * (1 - Math.exp(-delta / (wanted > s.level ? 45 : 150)));

  if (!reduced) s.deformation += (delta / 1000) * (0.8 + s.thinking * 0.5);
  const unit = 1 / 1.6;
  const awakeSize = 0.052 + 0.948 * s.awake;
  const breath = 1 + Math.sin(time) * 0.025 + s.envelope * 0.055;
  const saturation = (0.36 + s.vivid * 0.59) * (1 - 0.92 * s.offline);
  const lightness = 0.36 + s.vivid * 0.18 - 0.04 * s.offline;
  return {
    scale: awakeSize * breath * unit,
    offset: [Math.sin(time * 0.39) * 0.05 * s.awake * unit, (Math.sin(time * 0.65) * 0.065 * s.awake - pose.lift / 155) * unit],
    halo: awakeSize,
    time,
    deformation: s.deformation,
    energy: s.energy,
    speech: s.envelope + s.listening * (0.5 + 0.5 * Math.sin(time * 2.8)) * 0.15,
    shimmer: reduced ? 0 : Math.min(1, s.speaking * (0.35 + 0.5 * Math.min(1, s.envelope * 1.6))),
    hop: pose,
    color: hslToLinear(((s.hue % 360) + 360) % 360, saturation, lightness),
    accent: hslToLinear(((s.accent % 360) + 360) % 360, saturation * 0.92, Math.min(0.72, lightness + 0.04)),
    level: s.level > 0.01 || listening ? s.level : 0,
    moving: !reduced || s.awake < 0.999 || Math.abs(s.hue - target.hue) > 0.5,
  };
}



function compile(gl, vertex, fragment, attribute) {
  const shader = (type, source) => {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, source);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const v = shader(gl.VERTEX_SHADER, vertex);
  const f = shader(gl.FRAGMENT_SHADER, fragment);
  const program = gl.createProgram();
  if (!v || !f || !program) return null;
  gl.attachShader(program, v);
  gl.attachShader(program, f);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  const u = {};
  const count = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < count; i++) {
    const name = gl.getActiveUniform(program, i)?.name;
    if (name) u[name] = gl.getUniformLocation(program, name);
  }
  return { program, u, attribute: gl.getAttribLocation(program, attribute) };
}

/** Une sphère unité, 56 × 80 facettes, en triangles indexés. */
function sphere(gl) {
  const lat = 56;
  const lon = 80;
  const positions = [];
  const indices = [];
  for (let i = 0; i <= lat; i++) {
    const theta = (i / lat) * Math.PI;
    for (let j = 0; j <= lon; j++) {
      const phi = (j / lon) * Math.PI * 2;
      positions.push(Math.sin(theta) * Math.cos(phi), Math.cos(theta), Math.sin(theta) * Math.sin(phi));
    }
  }
  for (let i = 0; i < lat; i++) {
    for (let j = 0; j < lon; j++) {
      const a = i * (lon + 1) + j;
      const b = a + lon + 1;
      indices.push(a, b, a + 1, b, b + 1, a + 1);
    }
  }
  const vertices = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vertices);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.STATIC_DRAW);
  const elements = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, elements);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
  return { vertices, elements, count: indices.length };
}


/** Le dessin sur ce canevas, ou null sans WebGL (l'orbe devient alors un disque dégradé). */
function createOrbRenderer(canvas) {
  const gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: true });
  if (!gl) return null;
  const orb = compile(gl, ORB_VERTEX, ORB_FRAGMENT, "position");
  const halo = compile(gl, QUAD_VERTEX, HALO_FRAGMENT, "corner");
  const line = compile(gl, QUAD_VERTEX, LINE_FRAGMENT, "corner");
  if (!orb || !halo || !line) return null;
  const mesh = sphere(gl);
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

  const bindQuad = (p) => {
    gl.useProgram(p.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.enableVertexAttribArray(p.attribute);
    gl.vertexAttribPointer(p.attribute, 2, gl.FLOAT, false, 0, 0);
  };

  return {
    draw(f) {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const css = canvas.clientWidth;
      const px = Math.max(1, Math.round(css * ratio));
      if (canvas.width !== px) {
        canvas.width = px;
        canvas.height = px;
      }
      gl.viewport(0, 0, px, px);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

      gl.disable(gl.DEPTH_TEST);
      bindQuad(halo);
      gl.uniform2f(halo.u.uCenter, f.offset[0], f.offset[1]);
      gl.uniform2f(halo.u.uHalf, f.halo, f.halo);
      gl.uniform3fv(halo.u.uColor, f.color);
      gl.uniform3fv(halo.u.uAccent, f.accent);
      gl.uniform1f(halo.u.uEnergy, f.energy);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

      gl.enable(gl.DEPTH_TEST);
      gl.useProgram(orb.program);
      gl.bindBuffer(gl.ARRAY_BUFFER, mesh.vertices);
      gl.enableVertexAttribArray(orb.attribute);
      gl.vertexAttribPointer(orb.attribute, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.elements);
      gl.uniform1f(orb.u.uTime, f.deformation);
      gl.uniform1f(orb.u.uEnergy, f.energy);
      gl.uniform1f(orb.u.uSpeech, f.speech);
      gl.uniform1f(orb.u.uTwist, f.hop.twist);
      gl.uniform1f(orb.u.uFlow, f.hop.flow);
      gl.uniform2f(orb.u.uStretch, f.hop.sx, f.hop.sy);
      gl.uniform1f(orb.u.uScale, f.scale);
      gl.uniform2f(orb.u.uOffset, f.offset[0], f.offset[1]);
      gl.uniform3fv(orb.u.uColor, f.color);
      gl.uniform3fv(orb.u.uAccent, f.accent);
      gl.uniform1f(orb.u.uShimmer, f.shimmer);
      gl.colorMask(false, false, false, false);
      gl.depthFunc(gl.LESS);
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
      gl.colorMask(true, true, true, true);
      gl.depthFunc(gl.LEQUAL);
      gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
      gl.disableVertexAttribArray(orb.attribute);

      // le ruban sous une grande orbe seulement : sous celle du champ (50 px), il la cacherait
      if (f.level > 0 && css >= 180) {
        gl.disable(gl.DEPTH_TEST);
        bindQuad(line);
        const width = Math.min(190, css * 0.46);
        gl.uniform2f(line.u.uCenter, f.offset[0], f.offset[1] - 1.25 / 1.6);
        gl.uniform2f(line.u.uHalf, width / css, 40 / css);
        gl.uniform2f(line.u.uSize, width, 40);
        gl.uniform1f(line.u.uTime, f.time);
        gl.uniform1f(line.u.uLevel, f.level);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
    },
    dispose() {
      gl.deleteBuffer(mesh.vertices);
      gl.deleteBuffer(mesh.elements);
      gl.deleteBuffer(quad);
      const lose = gl.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
    },
  };
}

/**
 * Monte l'orbe sur `canvas`. Sans WebGL, le canevas se cache et la classe `orb-flat` de son parent
 * montre un disque dégradé à la place. `set(humeur)` change l'humeur, `level(x)` donne le niveau
 * réel du micro (0 à 1) pendant l'écoute, `dispose()` rend le contexte WebGL.
 */
export function mountOrb(canvas, mood = "idle") {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = createOrbRenderer(canvas);
  let frame = 0;
  let mic = null;
  const holder = canvas.parentElement;
  if (holder) holder.dataset.mood = mood;
  if (!renderer) {
    canvas.hidden = true;
    if (holder) holder.classList.add("orb-flat");
    return { set: (m) => { mood = m; if (holder) holder.dataset.mood = m; }, level() {}, dispose() {} };
  }
  const state = startState(performance.now(), mood, reduced);
  const draw = (now) => {
    frame = 0;
    const f = advance(state, now, mood, reduced, mic);
    renderer.draw(f);
    if (f.moving && !document.hidden) frame = requestAnimationFrame(draw);
  };
  const resume = () => {
    if (!frame && !document.hidden) frame = requestAnimationFrame(draw);
  };
  document.addEventListener("visibilitychange", resume);
  resume();
  return {
    set(m) {
      if (m === mood) return;
      mood = m;
      if (holder) holder.dataset.mood = m;
      resume();
    },
    level(x) {
      mic = x;
    },
    dispose() {
      document.removeEventListener("visibilitychange", resume);
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      renderer.dispose();
    },
  };
}
