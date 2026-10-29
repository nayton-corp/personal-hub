"""Collecteur Revolut (Enable Banking) avec une fausse API : liaison, reprise complète, synchro,
quota journalier, consentement expiré, JWT."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from hub.collectors.base import Failure
from hub.collectors.revolut import flow
from hub.collectors.revolut.enable_banking import EnableBanking, jwt
from hub.collectors.runtime import execute
from hub.kernel.clock import iso, utcnow
from tests.collectors.conftest import FakeHub

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()

ACCOUNT = {
    "uid": "uid-1",
    "account_id": {"iban": "LT601010012345678901"},
    "currency": "CHF",
    "cash_account_type": "CACC",
    "product": "Current",
    "identification_hash": "hash-chf-current-0001",
}


def tx(ref: str, amount: str, cdi: str, on: str, status: str = "BOOK") -> dict[str, Any]:
    return {
        "entry_reference": ref,
        "transaction_amount": {"currency": "CHF", "amount": amount},
        "credit_debit_indicator": cdi,
        "status": status,
        "booking_date": on,
        "creditor": {"name": "Commerce fictif"},
        "remittance_information": ["Achat fictif"],
    }


class FakeEB:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, list[str]]]] = []
        self.auth: dict[str, Any] = {}
        self.status = 200
        self.session_status = "AUTHORIZED"
        self.txs = [
            tx("r1", "12.50", "DBIT", "2026-10-20"),
            tx("r2", "100.00", "CRDT", "2026-10-21"),
        ]

    def __call__(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        parts = urlsplit(url)
        q = parse_qs(parts.query)
        self.calls.append((method, parts.path, q))
        assert headers["Authorization"].startswith("Bearer ey")
        if self.status != 200:
            return self.status, b"{}"
        path = parts.path
        if path == "/aspsps":
            body: Any = {
                "aspsps": [
                    {"name": "Revolut", "country": "LT", "maximum_consent_validity": 90 * 86_400}
                ]
            }
        elif path == "/auth":
            sent = json.loads(data or b"{}")
            self.auth = sent
            body = {"url": f"https://bank.example.invalid/auth?state={sent['state']}"}
        elif path == "/sessions":
            body = {
                "session_id": "sess-1",
                "accounts": [ACCOUNT],
                "access": {"valid_until": iso(utcnow() + timedelta(days=90))},
            }
        elif path == "/sessions/sess-1":
            body = {"status": self.session_status}
        elif path.endswith("/balances"):
            body = {
                "balances": [
                    {
                        "balance_type": "ITBD",
                        "balance_amount": {"currency": "CHF", "amount": "187.50"},
                        "reference_date": "2026-10-27",
                    }
                ]
            }
        elif path.endswith("/transactions"):
            if "continuation_key" not in q:
                body = {"transactions": self.txs[:1], "continuation_key": "page2"}
            else:
                body = {"transactions": self.txs[1:], "continuation_key": None}
        else:
            return 404, b"{}"
        return 200, json.dumps(body).encode()


@pytest.fixture
def eb() -> FakeEB:
    return FakeEB()


@pytest.fixture
def client(eb: FakeEB) -> EnableBanking:
    return EnableBanking("https://api.example.invalid", "app-test", PEM, eb)


@pytest.fixture
def no_sleep() -> Iterator[list[float]]:
    slept: list[float] = []
    return slept


def inbox_docs(root: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_bytes()) for p in sorted(root.glob("*.json"))]


def test_jwt_is_signed_rs256() -> None:
    token = jwt("app-test", PEM, now=1_800_000_000)
    head, body, sig = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    assert json.loads(base64.urlsafe_b64decode(pad(head))) == {
        "typ": "JWT",
        "alg": "RS256",
        "kid": "app-test",
    }
    claims = json.loads(base64.urlsafe_b64decode(pad(body)))
    assert claims["aud"] == "api.enablebanking.com"
    assert claims["exp"] - claims["iat"] == 3600
    KEY.public_key().verify(
        base64.urlsafe_b64decode(pad(sig)),
        f"{head}.{body}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_link_then_full_history(
    make_env, client: EnableBanking, eb: FakeEB, fake_hub: FakeHub
) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    shown: list[str] = []
    result = flow.link(
        env, "https://hub.example.ts.net/cb", shown.append, client, sleep=lambda _s: None
    )
    assert (result.outcome, result.files) == ("ok", 1)
    assert shown
    assert shown[0].startswith("https://bank.example.invalid/auth")
    auth = next(c for c in eb.calls if c[1] == "/auth")
    assert auth[0] == "POST"
    # un jour de marge sous le maximum de la banque (90 jours dans le faux Enable Banking)
    asked = eb.auth["access"]["valid_until"]
    assert iso(utcnow() + timedelta(days=88)) < asked < iso(utcnow() + timedelta(days=89, hours=1))
    tx_call = next(c for c in eb.calls if c[1].endswith("/transactions"))
    assert tx_call[2]["date_from"] == [flow.HISTORY_FROM]  # tout l'historique, tout de suite
    (doc,) = inbox_docs(env.inbox_root)
    assert doc["format"] == "hub.revolut.v1"
    assert doc["full_history"] is True
    assert len(doc["transactions"]) == 2  # deux pages
    assert "uid" not in doc["account"]
    assert env.memory.get("session_id") == "sess-1"


def test_scheduled_sync_overlap_and_unchanged(make_env, client: EnableBanking, eb: FakeEB) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    flow.link(env, "https://x.invalid/cb", lambda _u: None, client, sleep=lambda _s: None)
    eb.calls.clear()
    again = flow.run(env, "run", client)
    assert again.outcome == "nothing_new"  # mêmes écritures : rien de déposé
    tx_call = next(c for c in eb.calls if c[1].endswith("/transactions"))
    assert tx_call[2]["date_from"] == ["2026-10-17"]  # J-10
    eb.txs.append(tx("r3", "5.00", "DBIT", "2026-10-26"))
    assert flow.run(env, "run", client).files == 1


def test_daily_quota(make_env, client: EnableBanking) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    flow.link(env, "https://x.invalid/cb", lambda _u: None, client, sleep=lambda _s: None)
    outcomes = [flow.run(env, "run", client).detail for _ in range(4)]
    assert outcomes[-1] == "quota.day"  # liaison + 3 synchros = 4 appels à la banque


def test_without_consent_is_auth_error(make_env) -> None:  # type: ignore[no-untyped-def]
    result = execute(make_env("revolut"), "run")
    assert (result.outcome, result.detail) == ("auth_error", "consent.missing")


def test_expired_consent(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    env.memory.put("session_id", "sess-1")
    env.memory.put("valid_until", "2020-01-01T00:00:00.000Z")
    with pytest.raises(Failure) as exc:
        flow.run(env, "run")
    assert exc.value.detail == "consent.expired"


def test_revoked_consent_and_http_errors(make_env, client: EnableBanking, eb: FakeEB) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    flow.link(env, "https://x.invalid/cb", lambda _u: None, client, sleep=lambda _s: None)
    eb.session_status = "REVOKED"
    with pytest.raises(Failure) as exc:
        flow.run(env, "check", client)
    assert (exc.value.outcome, exc.value.detail) == ("auth_error", "consent.revoked")
    for status, outcome in (
        (401, "auth_error"),
        (429, "site_unavailable"),
        (503, "site_unavailable"),
    ):
        eb.status = status
        with pytest.raises(Failure) as exc:
            flow.run(env, "run", client)
        assert exc.value.outcome == outcome


def test_expiry_warning_once(make_env, client: EnableBanking, fake_hub: FakeHub) -> None:  # type: ignore[no-untyped-def]
    env = make_env("revolut")
    flow.link(env, "https://x.invalid/cb", lambda _u: None, client, sleep=lambda _s: None)
    env.memory.put("valid_until", iso(utcnow() + timedelta(days=3)))
    flow.run(env, "run", client)
    flow.run(env, "run", client)
    assert fake_hub.notified == ["revolut:consent_expiring"]


def test_link_times_out(make_env, client: EnableBanking, fake_hub: FakeHub) -> None:  # type: ignore[no-untyped-def]
    fake_hub.code = ""  # le navigateur ne revient jamais
    fake_hub.take_link = lambda _n, _s: None  # type: ignore[method-assign]
    with pytest.raises(Failure) as exc:
        flow.link(
            make_env("revolut"),
            "https://x.invalid/cb",
            lambda _u: None,
            client,
            wait_s=4,
            sleep=lambda _s: None,
        )
    assert exc.value.outcome == "auth_pending_timeout"
