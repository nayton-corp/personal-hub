"""Le service : POST /talk relayé par Domia (la forme que AssistantRelay envoie), les adresses autorisées seulement."""

import json
import urllib.error
import urllib.request

from domia_assistant.assistant import Assistant
from domia_assistant.llm import ScriptedModel
from domia_assistant.memory import Memory
from domia_assistant.server import serve
from domia_assistant.tools import build
from tests.fakes import FakeDomia


def post(url, body):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_talk_as_domia_relays_it():
    domia = FakeDomia()
    memory = Memory(":memory:")
    assistant = Assistant(domia, ScriptedModel([]), memory, lambda: build(domia, None, memory, None))
    server = serve(assistant, "127.0.0.1", 0, ("127.0.0.1",), lambda: {"domia": {"ok": True}})
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, answer = post(
            url + "/talk",
            {
                "text": "allume la cuisine",
                "room": None,
                "person": "robin",
                "client": "client_1",
                "correlation_id": "api-1",
            },
        )
        assert status == 200
        assert answer == {"answer": "C'est fait.", "done": ["Cuisine"], "proposals": [], "confirm": None}
        assert domia.gestures[0][3] == "robin"
        assert post(url + "/talk", {"nope": 1})[0] == 400
        with urllib.request.urlopen(url + "/health") as r:
            assert json.loads(r.read())["domia"] == {"ok": True}
    finally:
        server.shutdown()


def test_an_unknown_address_is_refused():
    domia = FakeDomia()
    memory = Memory(":memory:")
    assistant = Assistant(domia, ScriptedModel([]), memory, lambda: build(domia, None, memory, None))
    server = serve(assistant, "127.0.0.1", 0, ("192.168.0.63",), lambda: {})
    try:
        assert post(f"http://127.0.0.1:{server.server_address[1]}/talk", {"text": "allume la cuisine"})[0] == 403
        assert domia.gestures == []
    finally:
        server.shutdown()


def test_warm_prepares_the_model_and_retries_until_it_answers():
    import threading

    from domia_assistant.llm import ModelError, say
    from domia_assistant.server import warm

    class Late(ScriptedModel):
        def __init__(self):
            super().__init__([say("ok")])
            self.calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                raise ModelError("Ollama pas encore lancé")
            return super().chat(messages, tools)

    domia = FakeDomia()
    memory = Memory(":memory:")
    model = Late()
    assistant = Assistant(domia, model, memory, lambda: build(domia, None, memory, None))
    assert warm(assistant, threading.Event(), every=0) is True
    assert model.calls == 2
    messages, tools = model.requests[0]
    assert messages[0]["role"] == "system" and "La maison :" in messages[0]["content"]
    assert tools  # les mêmes outils que les vraies questions : c'est leur préfixe qui reste en cache


def test_keep_alive_goes_with_each_call():
    from domia_assistant.llm import OpenAICompatible

    sent = []
    model = OpenAICompatible("http://x/v1", "m", keep_alive="24h")
    model._post = lambda path, body: (
        sent.append(body) or {"choices": [{"message": {"content": "ok"}}], "data": [{"index": 0, "embedding": [1.0]}]}
    )
    model.chat([{"role": "user", "content": "x"}], [])
    model.embed(["x"], "e")
    assert [b["keep_alive"] for b in sent] == ["24h", "24h"]
    plain = OpenAICompatible("http://x/v1", "m")
    plain._post = lambda path, body: sent.append(body) or {"choices": [{"message": {"content": "ok"}}]}
    plain.chat([], [])
    assert "keep_alive" not in sent[-1]


def test_a_thinking_model_gets_its_effort_and_others_nothing():
    from domia_assistant.llm import OpenAICompatible

    sent = []
    for reasoning in ("low", None):
        model = OpenAICompatible("http://x/v1", "m", reasoning=reasoning)
        model._post = lambda path, body: sent.append(body) or {"choices": [{"message": {"content": "ok"}}]}
        model.chat([], [])
    assert sent[0]["reasoning_effort"] == "low" and "reasoning_effort" not in sent[1]


def test_web_search_sends_only_the_question_and_survives_an_absent_instance():
    import http.server
    import threading

    from domia_assistant.tools import Speaker, web_tools

    asked = []

    class Searx(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            asked.append(self.path)
            body = json.dumps(
                {"results": [{"title": "E24", "url": "https://x", "content": "vidange", "extra": 1}] * 7}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Searx)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        [tool] = web_tools(f"http://127.0.0.1:{httpd.server_address[1]}")
        found = tool.run({"query": "lave-vaisselle E24"}, Speaker())
        assert asked == ["/search?q=lave-vaisselle+E24&format=json"]
        assert len(found) == 5 and found[0] == {"title": "E24", "url": "https://x", "content": "vidange"}
    finally:
        httpd.shutdown()
    [down] = web_tools("http://127.0.0.1:9")
    assert "error" in down.run({"query": "x"}, Speaker())
