"""La ligne de commande : sans trace de pile ; la bibliothèque ne se lit plus en local (S12 du hub)."""

import pytest

from domia_assistant.__main__ import Parts, main


def test_the_local_library_is_no_longer_read(tmp_path, monkeypatch):
    """La bibliothèque vit dans le hub (S12) : un ~/Domia/Bibliothèque/ resté sur le disque n'est plus lu, et sans
    jeton `library` l'assistant n'a pas de bibliothèque du tout."""
    from domia_assistant.config import load

    monkeypatch.setenv("DOMIA_ASSISTANT_TOKEN", "t")
    home = tmp_path / "Domia"
    (home / "Bibliothèque").mkdir(parents=True)
    (home / "Bibliothèque" / "bail.md").write_text("Résiliation : quatre mois à l'avance.", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(f"domia: {{url: 'http://127.0.0.1:9'}}\nassistant: {{home: '{home}'}}\n", encoding="utf-8")
    assert Parts(load(config)).library is None
    with config.open("a", encoding="utf-8") as f:
        f.write("hub: {url: 'http://127.0.0.1:9', owners: [robin]}\n")
    assert Parts(load(config)).library is None  # ni hub.secrets ni hub.age_key : pas de jeton library
    with pytest.raises(SystemExit):
        main(["index", "--config", str(config)])


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
