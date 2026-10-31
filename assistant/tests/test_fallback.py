"""DeepSeek d'abord, Mistral local en repli (décision de Client 0 du 2026-10-31) : plus de crédit, une clé refusée, le
réseau coupé ou un délai dépassé, et la phrase repart sur le modèle local."""

from domia_assistant.llm import Fallback, ModelError, ScriptedModel, say


class Broken:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        raise ModelError("le modèle ne répond pas (HTTP Error 402: Payment Required)")


class Local(ScriptedModel):
    def embed(self, texts, model):
        return [[1.0]]

    def look(self, image, mime, question, model):
        return "plaque"


def test_the_local_model_answers_when_the_cloud_fails_then_the_cloud_rests_five_minutes():
    now = [0.0]
    cloud, local = Broken(), Local([say("local 1"), say("local 2"), say("local 3")])
    model = Fallback(cloud, local, clock=lambda: now[0])
    assert model.chat([], [])["content"] == "local 1" and model.last == "local" and cloud.calls == 1
    now[0] = 299
    assert model.chat([], [])["content"] == "local 2" and cloud.calls == 1  # pas d'attente du cloud à chaque phrase
    now[0] = 301
    assert model.chat([], [])["content"] == "local 3" and cloud.calls == 2  # retenté après la pause


def test_the_cloud_answers_when_it_works_and_vectors_and_vision_stay_local():
    model = Fallback(ScriptedModel([say("cloud")]), Local([]))
    assert model.chat([], [])["content"] == "cloud" and model.last == "primary"
    assert model.embed(["x"], "bge-m3") == [[1.0]] and model.look(b"", "image/png", "?", "gemma3") == "plaque"


def test_when_both_fail_the_error_reaches_the_loop_as_before():
    model = Fallback(Broken(), Local([]))
    try:
        model.chat([], [])
    except ModelError:
        pass
    else:
        raise AssertionError("une erreur du modèle local doit remonter")
