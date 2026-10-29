"""La ligne de commande : un modèle d'embeddings absent se dit, sans trace de pile."""

from domia_assistant.__main__ import Parts, main


def test_index_without_the_embeddings_model_says_which_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DOMIA_ASSISTANT_TOKEN", "t")
    home = tmp_path / "Domia"
    (home / "Bibliothèque" / "foyer").mkdir(parents=True)
    (home / "Bibliothèque" / "foyer" / "bail.md").write_text("Résiliation : quatre mois à l'avance.", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "domia: {url: 'http://127.0.0.1:9'}\n"
        "model: {url: 'http://127.0.0.1:9/v1', name: m, embeddings: bge-m3}\n"
        f"assistant: {{home: '{home}'}}\n",
        encoding="utf-8",
    )

    assert main(["index", "--config", str(config)]) == 1
    assert "ollama pull bge-m3" in capsys.readouterr().err


def test_check_says_when_the_bridge_answers_without_the_macos_access(tmp_path, monkeypatch):
    from domia_assistant.__main__ import Parts
    from domia_assistant.config import load

    monkeypatch.setenv("DOMIA_ASSISTANT_TOKEN", "t")
    config = tmp_path / "config.yaml"
    config.write_text(f"domia: {{url: 'http://127.0.0.1:9'}}\nassistant: {{home: '{tmp_path}'}}\n", encoding="utf-8")
    parts = Parts(load(config))
    parts.domia.house = lambda: {"situation": {"value": "DAY"}}
    parts.agenda.status = lambda: {
        "reminders": False,
        "calendar": False,
    }  # lancé par launchd : macOS n'a autorisé que le Terminal
    reminders = parts.status()["reminders"]
    assert reminders["ok"] is False and "Confidentialité" in reminders["error"]
    parts.agenda.status = lambda: {"reminders": True, "calendar": True}
    assert parts.status()["reminders"] == {"ok": True, "calendar": True}


def test_the_bench_keeps_its_own_database(tmp_path, monkeypatch):
    import dataclasses

    from domia_assistant.config import load

    monkeypatch.setenv("DOMIA_ASSISTANT_TOKEN", "t")
    config = tmp_path / "config.yaml"
    config.write_text(f"assistant: {{home: '{tmp_path}'}}\n", encoding="utf-8")
    settings = load(config)
    assert settings.database == tmp_path / "assistant.sqlite"
    assert dataclasses.replace(settings, database_file="banc.sqlite").database == tmp_path / "banc.sqlite"


def test_the_model_stays_loaded_unless_told_otherwise(tmp_path, monkeypatch):
    from domia_assistant.config import load

    monkeypatch.setenv("DOMIA_ASSISTANT_TOKEN", "t")
    config = tmp_path / "config.yaml"
    config.write_text(f"assistant: {{home: '{tmp_path}'}}\n", encoding="utf-8")
    assert load(config).keep_alive == "24h"
    assert Parts(load(config)).model.keep_alive == "24h"
    config.write_text(f"model: {{keep_alive: null}}\nassistant: {{home: '{tmp_path}'}}\n", encoding="utf-8")
    assert load(config).keep_alive is None
