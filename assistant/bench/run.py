"""Le banc d'essai (spec §13) : `python bench/run.py [--config config.essai.yaml] [--only f1,c2] [--set …]`.

Joue chaque cas de cases.yaml contre l'essai (Domia et Mock HA de compose.essai.yml, jamais la vraie maison), avec le
modèle de la config ; mesure la réussite par famille, le temps de réponse et les erreurs graves (un geste non demandé,
qui doivent être à zéro). Écrit le résultat dans bench/results/<modèle>-<date>.md. Claude, la référence, se joue à la
main par Claude Desktop branché au serveur MCP (décision 4)."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from domia_assistant.__main__ import Parts  # noqa: E402
from domia_assistant.config import Settings, load  # noqa: E402
from domia_assistant.grammar import normalize  # noqa: E402
from domia_assistant.tools import Speaker, Toolbox  # noqa: E402


def matches(expected: dict, got: tuple) -> bool:
    method, path, body = got
    if expected.get("method") and expected["method"] != method:
        return False
    if expected["path"] != path:
        return False
    return all((body or {}).get(k) == v for k, v in (expected.get("body") or {}).items())


def missing(case: dict, house: dict) -> list[str]:
    """Les objets attendus par le cas qui manquent à l'essai (/api/<sorte>/<id>/commands)."""
    known = {r["id"] for r in house.get("rooms", [])} | {m["id"] for m in house.get("machines", []) or []}
    for room in house.get("rooms", []):
        for key in ("lights", "appliances", "covers", "emitters"):
            known |= {o["id"] for o in room.get(key, []) or []}
    out = []
    for e in (case.get("gestures") or []) + (case.get("one_of") or []):
        parts = e["path"].strip("/").split("/")
        if len(parts) == 4 and parts[3] == "commands" and parts[2] not in known:
            out.append(parts[2])
    return out


def judge(
    case: dict, gestures: list[tuple], tools: list[str], model_calls: int, answer: str, worked: set[str] | None = None
) -> tuple[bool, list[str], int]:
    """(réussi, raisons, erreurs graves). Un outil attendu ne compte que s'il a rendu un résultat sans erreur."""
    why = []
    expected = case.get("gestures") or []
    either = case.get("one_of") or []
    tolerated = expected + either + (case.get("allowed") or [])
    grave = 0
    for g in gestures:
        if not any(matches(e, g) for e in tolerated):
            grave += 1
            why.append(f"geste non demandé : {g[0]} {g[1]} {g[2]}")
    for e in expected:
        if not any(matches(e, g) for g in gestures):
            why.append(f"geste manquant : {e['path']} {e.get('body', '')}")
    if either and not any(matches(e, g) for e in either for g in gestures):
        why.append("geste manquant : un de " + ", ".join(f"{e['path']} {e.get('body', '')}".strip() for e in either))
    if case.get("fast") and model_calls:
        why.append("le modèle a été appelé")
    for t in case.get("tools") or []:
        if t not in tools:
            why.append(f"outil non appelé : {t}")
        elif worked is not None and t not in worked:
            why.append(f"outil en erreur : {t}")
    for w in case.get("words") or []:
        if w not in normalize(answer):
            why.append(f"mot absent : {w}")
    return not why, why, grave


def read_only(case: dict) -> dict:
    """Sans le droit d'écrire (`assistant.settings_write`), une demande de réglage ne change rien et dit où le
    changer."""
    return {**{k: v for k, v in case.items() if k != "tools"}, "none": True, "words": ["reglages"]}


def expand(spec: dict, variants: dict, which: str) -> list[dict]:
    """Les phrases à jouer : `cases` la phrase de chaque cas, `variants` ses autres façons de le dire, `control` les
    phrases de contrôle, `dev` les deux premières, `all` toutes. Une variante garde les attentes de son cas, sauf la
    voie rapide (le modèle peut la prendre) ; son id est celui du cas suivi de .v1, .v2 ou .k1."""
    out = []
    for case in spec["cases"]:
        more = variants.get(case["id"]) or {}
        if which in ("cases", "dev", "all"):
            out.append(case)
        for tag, key in (("v", "variants"), ("k", "control")):
            if (key == "variants" and which not in ("variants", "dev", "all")) or (
                key == "control" and which not in ("control", "all")
            ):
                continue
            for n, text in enumerate(more.get(key) or [], 1):
                out.append(
                    {
                        **{k: v for k, v in case.items() if k != "fast"},
                        "id": f"{case['id']}.{tag}{n}",
                        "text": text,
                        "intent": case["id"],
                    }
                )
    return out


def isolated(settings: Settings) -> Settings:
    """Le banc a son propre dossier (base, à-trier), jamais celui du foyer, et ne joint jamais le hub :
    le seul hub est le vrai, ses outils y créeraient des propositions. Le 25.10, un banc a écrit trois
    fiches de test dans la vraie bibliothèque, par le dossier partagé."""
    home = Path(tempfile.mkdtemp(prefix="banc-"))
    return dataclasses.replace(settings, home=home, database_file="banc.sqlite", hub=None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=HERE.parent / "config.essai.yaml")
    parser.add_argument("--only", help="des ids de cas : leurs variantes suivent leur cas")
    parser.add_argument(
        "--set",
        default="all",
        choices=("cases", "variants", "control", "dev", "all"),
        help="dev pour corriger (cas et variantes), control pour vérifier, all la nuit",
    )
    parser.add_argument("--not-the-essai", action="store_true", help="une autre adresse d'essai que le port 3001")
    args = parser.parse_args()
    spec = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    variants = yaml.safe_load((HERE / "variants.yaml").read_text(encoding="utf-8")) or {}
    parts = Parts(isolated(load(args.config)))
    logging.basicConfig(level=logging.INFO, format="    %(message)s")  # la durée de chaque appel au modèle
    if not parts.settings.domia_url.endswith(":3001") and not args.not_the_essai:
        print("le banc tourne contre l'essai (port 3001), jamais contre la vraie maison", file=sys.stderr)
        return 2
    gestures: list[tuple] = []
    tools: list[str] = []
    calls = [0]
    real_gesture = parts.domia.gesture

    def gesture(method, path, body, person):
        gestures.append((method, path, body))
        return real_gesture(method, path, body, person)

    parts.domia.gesture = gesture  # type: ignore[method-assign]
    real_chat = parts.model.chat

    def chat(messages, schemas):
        calls[0] += 1
        message = real_chat(messages, schemas)
        tools.extend(c["function"]["name"] for c in message.get("tool_calls") or [])
        return message

    parts.model.chat = chat  # type: ignore[method-assign]
    worked: set[str] = set()
    real_run = Toolbox.run

    def run(self, name, args, who):
        result = real_run(self, name, args, who)
        if not (isinstance(result, dict) and "error" in result):
            worked.add(name)
        return result

    Toolbox.run = run  # type: ignore[method-assign]
    only = set(args.only.split(",")) if args.only else None
    by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows, times, graves, skipped = [], [], 0, []
    intents: dict[str, list[bool]] = defaultdict(list)
    house = parts.domia.house()
    for case in expand(spec, variants, args.set):
        if case["family"] == "reglage" and not parts.settings.settings_write:
            case = read_only(case)
        if only and case.get("intent", case["id"]) not in only:
            continue
        absent = missing(case, house)
        if absent:
            skipped.append(f"{case['id']} ({', '.join(absent)})")
            print(f"- {case['id']:4} ignoré : absent de l'essai : {', '.join(absent)}")
            continue
        real_gesture("PUT", "/api/situation", {"value": "DAY"}, None)
        gestures.clear()
        tools.clear()
        worked.clear()
        calls[0] = 0
        who = Speaker(person=spec.get("person"), client=f"bench-{case['id']}")
        started = time.monotonic()
        answer = parts.assistant.talk(case["text"], who)
        for follow in case.get("then") or []:
            answer = parts.assistant.talk(follow, who)
        elapsed = time.monotonic() - started
        ok, why, grave = judge(case, list(gestures), list(tools), calls[0], answer.get("answer", ""), set(worked))
        graves += grave
        by_family[case["family"]][0] += ok
        by_family[case["family"]][1] += 1
        intents[case.get("intent", case["id"])].append(ok)
        times.append((case["family"], elapsed))
        rows.append((case["id"], case["family"], ok, round(elapsed, 2), answer.get("answer", ""), "; ".join(why)))
        print(
            f"{'✓' if ok else '✗'} {case['id']:4} {elapsed:5.1f} s  {answer.get('answer', '')[:70]}  {'; '.join(why)}"
        )
    out = (
        HERE
        / "results"
        / f"{parts.settings.model.replace('/', '_').replace(':', '_')}-{datetime.now():%Y-%m-%d-%H%M}.md"
    )
    out.parent.mkdir(exist_ok=True)
    steady = sum(all(v) for v in intents.values())
    lines = [
        f"# Banc : {parts.settings.model} ({args.set})",
        "",
        f"Erreurs graves : **{graves}**",
        "",
        f"Intentions réussies sous toutes leurs formulations : **{steady}/{len(intents)}**",
        "",
    ]
    if skipped:
        lines += [f"Ignorés, objet absent de l'essai : {'; '.join(skipped)}", ""]
    lines += ["| Famille | Réussis | Temps médian | Temps max |", "|---|---|---|---|"]
    for family, (good, total) in by_family.items():
        ts = sorted(t for f, t in times if f == family)
        lines.append(f"| {family} | {good}/{total} | {ts[len(ts) // 2]:.1f} s | {ts[-1]:.1f} s |")
    lines += ["", "| Cas | Famille | OK | Temps | Réponse | Écarts |", "|---|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {'oui' if r[2] else 'non'} | {r[3]} s | {r[4][:80]} | {r[5]} |" for r in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nerreurs graves : {graves} ; résultat : {out}")
    return 0 if graves == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
