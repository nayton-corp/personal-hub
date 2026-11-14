// L'avatar d'une institution (connexion, compte à ajouter) : son logo, sinon son sigle et sa
// teinte quand on la connaît, sinon ses initiales.
import { el, initials } from "../../format.js";
import { brandColors, brandSvg, instLook, logoImg } from "./meta.js";

export function instAv(key, label, cls = "av") {
  const l = instLook(key) || instLook(label);
  if (!l) return el("div", cls, initials(label));
  if (l.logo || l.brand) {
    const av = el("div", `ibox ${l.logo ? "logo" : "brand"}`, "");
    if (!l.logo) for (const [k, v] of Object.entries(brandColors(l.brand))) av.style.setProperty(`--${k}`, v);
    av.innerHTML = l.logo ? logoImg(l.logo) : brandSvg(l.brand); // fichiers et tracés embarqués, pas de donnée utilisateur
    av.setAttribute("aria-hidden", "true");
    return av;
  }
  const av = el("div", `ibox tint${l.t.length > 2 ? " wm-box" : ""}`, l.t);
  av.style.setProperty("--c", l.c);
  av.setAttribute("aria-hidden", "true");
  return av;
}
