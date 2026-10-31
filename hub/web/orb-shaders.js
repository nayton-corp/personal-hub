// Les shaders de l'orbe (orb.js), repris de Domia : la sphère déformée, son halo et le ruban
// du micro sous une grande orbe.

export const ORB_VERTEX = `
attribute vec3 position;
uniform float uTime, uEnergy, uSpeech, uTwist, uFlow, uScale;
uniform vec2 uStretch, uOffset;
varying vec3 vNormal;
varying vec3 vSurface;
vec3 deform(vec3 p) {
  float waves = sin(p.x * 3.1 + uTime * 0.65) * sin(p.y * 2.7 - uTime * 0.48)
    + 0.5 * sin(p.z * 3.5 + p.y * 1.8 + uTime * 0.55);
  p *= 1.0 + waves * (0.055 + uEnergy * 0.035) + uSpeech * 0.07 * sin(p.y * 4.0 + uTime * 2.0);
  float twist = uTwist * (p.y * 0.95 + sin(p.y * 2.3 - uFlow) * 0.32);
  p.xz = mat2(cos(twist), -sin(twist), sin(twist), cos(twist)) * p.xz;
  p.x += uTwist * 0.17 * sin(p.y * 3.0 - uFlow) * max(0.0, 1.0 - p.y * p.y);
  p.y += uTwist * 0.08 * sin(p.x * 3.5 + uFlow);
  p.x *= 1.0 + (uStretch.x - 1.0) * (0.7 + 0.3 * p.y);
  p.y *= 1.0 + (uStretch.y - 1.0) * (0.7 + 0.3 * p.x);
  return p;
}
void main() {
  vec3 n = normalize(position);
  vec3 tangent = normalize(cross(abs(n.y) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0), n));
  vec3 bitangent = normalize(cross(n, tangent));
  vec3 p = deform(position);
  // les normales recalculées sur la peau déformée : la lumière suit la matière
  vec3 dt = deform(position + tangent * 0.004) - p;
  vec3 db = deform(position + bitangent * 0.004) - p;
  vNormal = normalize(cross(dt, db));
  vSurface = p;
  gl_Position = vec4(p.xy * uScale + uOffset, -p.z * 0.3, 1.0);
}`;

export const ORB_FRAGMENT = `
precision highp float;
uniform vec3 uColor, uAccent;
uniform float uTime, uEnergy, uSpeech, uShimmer;
varying vec3 vNormal;
varying vec3 vSurface;
void main() {
  vec3 n = normalize(vNormal);
  vec3 view = vec3(0.0, 0.0, 1.0);
  float facing = max(dot(n, view), 0.0);
  float fresnel = pow(1.0 - facing, 2.5);
  vec3 light = normalize(vec3(-0.7, 0.85, 1.4));
  float diffuse = max(dot(n, light), 0.0);
  float reflection = pow(max(dot(n, normalize(light + view)), 0.0), 56.0);
  float broadReflection = pow(max(dot(n, normalize(vec3(0.8, -0.5, 1.1))), 0.0), 12.0);
  float current = 0.5 + 0.5 * sin(vSurface.y * 4.0 + vSurface.x * 2.5 + sin(vSurface.z * 4.0 + uTime * 0.35));
  vec3 tint = mix(uColor, uAccent, smoothstep(-0.8, 0.8, vSurface.x - vSurface.y * 0.55));
  vec3 color = tint * (0.2 + diffuse * 0.43 + current * 0.12);
  color += mix(uAccent, uColor, facing) * fresnel * (0.82 + uEnergy * 0.34);
  color += mix(uColor, vec3(1.0), 0.3) * reflection * 0.7;
  color += uAccent * broadReflection * 0.23;
  float flowBand = 0.5 + 0.5 * sin(vSurface.y * 6.0 - uTime * 2.2 + vSurface.x * 2.0);
  vec3 iridescence = 0.5 + 0.5 * cos(vec3(0.0, 2.094, 4.188) + vSurface.y * 5.0 + uTime * 1.4);
  color += mix(uColor, iridescence, 0.3) * flowBand * uShimmer * 0.3;
  color += uColor * pow(facing, 9.0) * (0.08 + uSpeech * 0.17);
  float alpha = 0.88 + fresnel * 0.12;
  color = pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.2));
  gl_FragColor = vec4(color * alpha, alpha);
}`;

export const QUAD_VERTEX = `
attribute vec2 corner;
uniform vec2 uCenter, uHalf;
varying vec2 vUv;
void main() {
  vUv = corner * 0.5 + 0.5;
  gl_Position = vec4(uCenter + corner * uHalf, 0.99, 1.0);
}`;

export const HALO_FRAGMENT = `
precision highp float;
uniform vec3 uColor, uAccent;
uniform float uEnergy;
varying vec2 vUv;
void main() {
  vec2 p = (vUv - 0.5) * 2.0;
  float d = length(p);
  float band = exp(-pow((d - 0.5) * 3.3, 2.0));
  float fade = 1.0 - smoothstep(0.7, 1.0, d);
  vec3 color = mix(uColor, uAccent, smoothstep(-0.8, 0.8, p.x + p.y * 0.5));
  float alpha = band * fade * (0.22 + uEnergy * 0.16);
  color = pow(clamp(color, 0.0, 1.0), vec3(1.0 / 2.2));
  gl_FragColor = vec4(color * alpha, alpha);
}`;

export const LINE_FRAGMENT = `
precision highp float;
uniform float uTime, uLevel;
uniform vec2 uSize;
varying vec2 vUv;
void main() {
  vec2 p = (vUv - 0.5) * uSize;
  float envelope = pow(max(0.0, sin(vUv.x * 3.14159265)), 1.8);
  float wave = sin(vUv.x * 23.0 - uTime * 16.0) * 0.65 + sin(vUv.x * 37.0 + uTime * 11.0) * 0.35;
  float dist = abs(p.y - wave * envelope * uLevel * 12.0);
  float core = 1.0 - smoothstep(0.65, 1.5, dist);
  float glow = exp(-dist * 0.5) * uLevel * 0.35;
  float ends = smoothstep(0.0, 0.08, vUv.x) * (1.0 - smoothstep(0.92, 1.0, vUv.x));
  float alpha = clamp((core * (0.16 + uLevel * 0.8) + glow) * ends, 0.0, 1.0);
  vec3 color = mix(vec3(0.44, 0.92, 0.87), vec3(0.83, 1.0, 0.97), uLevel);
  gl_FragColor = vec4(color * alpha, alpha);
}`;
