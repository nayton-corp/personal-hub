// Bloc d'accueil du domaine factice : la coquille lui donne son conteneur.
import { fill } from "./ui.js";

export function render(box) {
  fill(box, '<section class="card"><h2 class="section-title">Démo à l\'accueil</h2><p class="note">Un bloc venu du manifeste.</p></section>');
}
