from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from hub.collectors.base import CollectorConfig, Kind, Result
from hub.collectors.runtime import Env
from tests.collectors.fakebank import Bank, serve


@dataclass
class FakeHub:
    """Remplace l'API du hub : état, runs déclarés, notifications, liaisons."""

    mode: str = "enabled"
    check_requested: bool = False
    runs: list[tuple[str, str, str]] = field(default_factory=list)
    notified: list[str] = field(default_factory=list)
    links: dict[str, str | None] = field(default_factory=dict)
    code: str = "code-retour"

    def state(self, name: str) -> dict[str, Any]:
        return {"name": name, "mode": self.mode, "check_requested": self.check_requested}

    def report(self, name: str, kind: Kind, result: Result, started: str, ended: str) -> None:
        self.runs.append((name, kind, result.outcome))

    def notify(self, name: str, event: str) -> bool:
        self.notified.append(f"{name}:{event}")
        return True

    def register_link(self, name: str, state: str) -> str:
        self.links[state] = None
        return "2026-10-27T18:00:00.000Z"

    def take_link(self, name: str, state: str) -> str | None:
        # le navigateur revient au deuxième passage
        if self.links.get(state) is None:
            self.links[state] = self.code
            return None
        return self.links[state]


@pytest.fixture
def bank() -> Bank:
    return Bank()


@pytest.fixture
def site(bank: Bank) -> Iterator[str]:
    with serve(bank) as url:
        yield url


@pytest.fixture
def fake_hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def make_env(tmp_path: Path, site: str, fake_hub: FakeHub):  # type: ignore[no-untyped-def]
    def _make(name: str, creds: dict[str, Any] | None = None, **cfg: Any) -> Env:
        urls = {
            "bcf.url": f"{site}/login",
            "viac.url": f"{site}/documents",
            "viac.documents": f"{site}/documents",
            **cfg.pop("urls", {}),
        }
        config = CollectorConfig(home=tmp_path / "collector", urls=urls, **cfg)
        default = {
            "bcf": {"contract": "123456", "password": "secret-test"},
            "viac": {"email": "test@example.invalid", "password": "secret-test"},
            "revolut": {"application_id": "app-test", "private_key": "x"},
            "ibkr": {"flex_token": "jeton-test", "query_id": "123456"},
            "market": {},
            "binance": {"api_key": "cle-test", "api_secret": "secret-test"},
            "kucoin": {"api_key": "cle-test", "api_secret": "secret-test", "passphrase": "phrase"},
            "coinbase": {"key_name": "organizations/o/apiKeys/k", "private_key": "x"},
        }[name]
        return Env(
            name,
            config,
            creds if creds is not None else default,
            tmp_path / "inbox",
            fake_hub,  # type: ignore[arg-type]
            today=date(2026, 10, 27),
        )

    return _make


@pytest.fixture(autouse=True)
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Les pauses du collecteur « market » (mempool.space), notées au lieu d'attendre."""
    from hub.collectors.market import flow

    seen: list[int] = []
    monkeypatch.setattr(flow, "sleep", seen.append)
    return seen
