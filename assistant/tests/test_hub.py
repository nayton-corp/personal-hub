"""Les outils du hub (chantier S10 du hub) : montrés et ouverts au seul propriétaire, jamais à Kim ; d'un domaine lu en
entier, rien n'est repris (une question d'argent n'obtient que des agrégats) ; sans hub, la maison reste."""

import json

from domia_assistant import hub
from domia_assistant.assistant import Assistant
from domia_assistant.config import load
from domia_assistant.llm import ScriptedModel, call, calls, say
from domia_assistant.memory import Memory
from domia_assistant.tools import Speaker, build
from tests.fakes import FakeDomia

ROBIN = Speaker(person="robin", client="client_phone")
KIM = Speaker(person="kim", client="client_kim")
TOTALS = {"month": "2026-10", "total": {"display": "412.30", "currency": "CHF"}, "categories": 9}


class FakeHub:
    """Le client du hub (`hub.brain.hubapi.HubApi`), en mémoire."""

    def __init__(self, full: bool = False):
        self.full = full
        self.called: list[tuple[str, str, dict]] = []

    def hello(self):
        return {
            "domains": [
                {
                    "domain": "finance",
                    "description": "Finances personnelles : dépenses, budget, patrimoine",
                    "instructions": "Montants en CHF, toujours avec la période.",
                    "tools": ["finance_month_totals"],
                    "aggregates_only": not self.full,
                },
                {
                    "domain": "documents",
                    "description": "Documents et fiches d'objets",
                    "instructions": "",
                    "tools": ["documents_search"],
                    "aggregates_only": False,
                },
            ],
            "profile": {"display_name": "Robin"},
        }

    def tools(self, domain):
        return [
            {
                "name": f"{domain}_month_totals" if domain == "finance" else f"{domain}_search",
                "description": "Totaux du mois par catégorie.",
                "input_schema": {"type": "object", "properties": {"month": {"type": "string"}}},
            }
        ]

    def call(self, domain, name, args):
        self.called.append((domain, name, args))
        return TOTALS


CFG = hub.HubSettings(url="http://hub", owners=("robin",), token="t")


def make(replies, api=None, cfg=CFG):
    domia, memory = FakeDomia(), Memory(":memory:")
    module = hub.build(cfg, api or FakeHub())
    model = ScriptedModel(list(replies))
    assistant = Assistant(domia, model, memory, lambda: build(domia, None, memory, None, hub=module), clock=lambda: 0.0)
    return assistant, model, module


def shown(model, i=0):
    return {t["function"]["name"] for t in model.requests[i][1]}


def test_the_owner_asks_a_money_question_and_gets_totals():
    api = FakeHub()
    assistant, model, _ = make(
        [calls(call("finance_month_totals", {"month": "2026-10"})), say("412.30 CHF en octobre.")], api
    )
    assert assistant.talk("combien j'ai dépensé en octobre ?", ROBIN)["answer"] == "412.30 CHF en octobre."
    assert "finance_month_totals" in shown(model)
    assert api.called == [("finance", "finance_month_totals", {"month": "2026-10"})]
    assert json.loads(model.requests[1][0][-1]["content"]) == TOTALS
    system = model.requests[0][0][0]["content"]
    assert "Le hub (des totaux, jamais une écriture" in system
    assert "finance : Montants en CHF" in system


def test_kim_never_sees_nor_reaches_a_hub_tool():
    api = FakeHub()
    assistant, model, _ = make([calls(call("finance_month_totals", {})), say("Je ne peux pas.")], api)
    assistant.talk("combien Robin a dépensé ?", KIM)
    assert not shown(model) & {"finance_month_totals", "documents_search"}
    assert "Le hub" not in model.requests[0][0][0]["content"]
    # même nommé par le modèle, l'outil n'existe pas pour Kim
    assert json.loads(model.requests[1][0][-1]["content"]) == {"error": "outil inconnu : finance_month_totals"}
    assert api.called == []
    # une voix de pièce, sans personne : pareil
    assistant.talk("combien en restaurants ?", Speaker(room="living"))
    assert api.called == []


def test_a_domain_read_in_full_is_left_out():
    module = hub.build(CFG, FakeHub(full=True))
    assert module.tools == []
    assert module.families == {}
    module = hub.build(CFG, FakeHub())
    assert [t.name for t in module.tools] == ["finance_month_totals"]  # documents : lu en entier, écarté
    opened = hub.build(hub.HubSettings("http://hub", ("robin",), full_domains=("documents",), token="t"), FakeHub())
    assert sorted(t.name for t in opened.tools) == ["documents_search", "finance_month_totals"]


def test_the_router_names_a_hub_domain_only_for_the_owner():
    domia, memory = FakeDomia(), Memory(":memory:")
    box = build(domia, None, memory, None, hub=hub.build(CFG, FakeHub()))
    assert "finance" in box.families(ROBIN)
    assert "finance" not in box.families(KIM)
    assert box.owner == Speaker(person="robin")
    assert {t["function"]["name"] for t in box.schemas(frozenset({"finance"}), ROBIN)} == {"finance_month_totals"}
    assert box.schemas(frozenset({"finance"}), KIM) == []


def test_warm_prepares_the_household_prefix_then_the_owner_one():
    assistant, model, _ = make([say("ok"), say("ok")])
    assistant.warm()
    assert len(model.requests) == 2
    assert "finance_month_totals" not in shown(model, 0)
    assert "finance_month_totals" in shown(model, 1)


def test_hub_errors_say_their_type_only():
    class Down(FakeHub):
        def call(self, domain, name, args):
            err = RuntimeError("détail")
            err.type = "hub.unreachable"  # type: ignore[attr-defined]
            raise err

    box = build(FakeDomia(), None, Memory(":memory:"), None, hub=hub.build(CFG, Down()))
    assert box.run("finance_month_totals", {}, ROBIN) == {"error": "hub : hub.unreachable"}


def test_config_reads_the_hub_section(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "hub:\n  url: http://127.0.0.1:8710/\n  owners: [robin]\n  secrets: ~/PersonalHub/brain.enc.yaml\n"
        "  age_key: ~/PersonalHub/key.txt\n",
        encoding="utf-8",
    )
    s = load(path, {"DOMIA_ASSISTANT_TOKEN": "x"})
    assert s.hub is not None
    assert (s.hub.url, s.hub.owners, s.hub.token) == ("http://127.0.0.1:8710", ("robin",), None)
    assert s.hub.secrets is not None and s.hub.secrets.name == "brain.enc.yaml"
    path.write_text("hub:\n  url: http://hub\n", encoding="utf-8")  # sans propriétaire : pas d'outils du hub
    assert load(path, {"DOMIA_ASSISTANT_TOKEN": "x"}).hub is None
    assert load(tmp_path / "absent.yaml", {"DOMIA_ASSISTANT_TOKEN": "x"}).hub is None


def test_without_the_hub_package_the_house_keeps_going(monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kw):
        if name.startswith("hub.brain"):
            raise ImportError(name)
        return real(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert hub.connect(CFG) is None


def test_the_token_comes_from_the_trial_variable_or_the_encrypted_secrets():
    assert hub.token(CFG) == "t"
    try:
        hub.token(hub.HubSettings("http://hub", ("robin",)))
    except RuntimeError as e:
        assert "HUB_ASSISTANT_TOKEN" in str(e)
    else:
        raise AssertionError("un jeton sans source")


def test_the_real_hub_client_fits(monkeypatch):
    """Avec le paquet du hub installé (la CI : pip install -e ..), le vrai client passe par les routes d'outils."""
    import pytest

    hubapi = pytest.importorskip("hub.brain.hubapi")
    fake = FakeHub()
    seen: list[tuple[str, str]] = []

    def transport(method, url, headers, data):
        seen.append((method, url))
        assert headers["Authorization"] == "Bearer t"
        path = url.split("/api/tools", 1)[1]
        if path == "":
            return 200, json.dumps(fake.hello()).encode()
        if method == "GET":
            return 200, json.dumps({"domain": path[1:], "items": fake.tools(path[1:])}).encode()
        return 200, json.dumps({"result": TOTALS}).encode()

    monkeypatch.setattr(hubapi, "urllib_transport", transport)
    module = hub.connect(CFG)
    assert module is not None
    assert module.tools[0].run({"month": "2026-10"}, ROBIN) == TOTALS
    assert seen[-1] == ("POST", "http://hub/api/tools/finance/finance_month_totals")
