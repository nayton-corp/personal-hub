import pytest

from hub.kernel.ids import Urn, actor, is_actor, new_id, urn
from hub.kernel.text import is_iban, mask_iban, normalize


def test_normalize() -> None:
    assert normalize("  Café   de la GARE\tZürich ") == "cafe de la gare zurich"
    assert normalize(None) == ""
    assert normalize("ﬁ") == "fi"  # NFKD


def test_mask_iban() -> None:
    assert mask_iban("CH93 0076 2011 6238 5295 7") == "CH93…957"
    assert mask_iban(None) is None
    assert mask_iban("CH9") == "…"
    assert is_iban("CH93 0076 2011 6238 5295 7")
    assert not is_iban("hello")


def test_urn_roundtrip() -> None:
    value = urn("finance", "entry", "en_ABC")
    assert value == "hub:finance:entry:en_ABC"
    assert str(Urn.parse(value)) == value
    with pytest.raises(ValueError, match="URN"):
        Urn.parse("finance:entry:1")
    with pytest.raises(ValueError, match="URN"):
        urn("Finance", "entry", "1")


def test_actor() -> None:
    assert actor("system", "importer") == "system:importer"
    assert is_actor("passkey:abc-_")
    assert not is_actor("root:x")
    with pytest.raises(ValueError, match="acteur"):
        actor("user", "x")


def test_new_id_is_ulid() -> None:
    a, b = new_id(), new_id("p_")
    assert len(a) == 26
    assert b.startswith("p_")
    assert a != new_id()
