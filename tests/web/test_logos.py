"""Les logos nommés par l'app et par les packs pays existent, et sont des SVG sans rien à aller
chercher ailleurs (CSP `img-src 'self'`, pas de service tiers à l'affichage)."""

from __future__ import annotations

import re
from pathlib import Path

from hub.domains.finance.packs.ch import PACK

WEB = Path(__file__).resolve().parents[2] / "hub" / "domains" / "finance" / "web"
LOGOS = WEB / "logos"


def _declared() -> set[str]:
    src = (WEB / "meta.js").read_text()
    block = re.search(r"const LOGOS = new Set\(\[(.*?)\]\);", src, re.S)
    assert block, "LOGOS introuvable dans meta.js"
    return set(re.findall(r'"([a-z0-9]+)"', block.group(1)))


def _pack() -> set[str]:
    pairs = [*PACK.merchant_logos, *PACK.fund_logos]
    return {logo for _, logo in pairs} | set(PACK.institution_logos.values())


def test_every_coin_logo_has_its_file_and_back() -> None:
    src = (WEB / "meta.js").read_text()
    block = re.search(r"const COINS = new Set\(\[(.*?)\]\);", src, re.S)
    assert block, "COINS introuvable dans meta.js"
    coins = set(re.findall(r'"([a-z0-9]+)"', block.group(1)))
    assert coins == {p.stem for p in (LOGOS / "coins").glob("*.svg")}


def test_every_declared_logo_has_its_file_and_back() -> None:
    files = {p.stem for p in LOGOS.glob("*.svg")}
    assert _declared() | _pack() == files


def test_the_rules_name_only_known_logos() -> None:
    src = (WEB / "meta.js").read_text()
    rules = src.split("const LOGOS")[1].split("const MERCHANT_BRANDS")[0]
    rules += src.split("const FUND_LOGOS")[1].split("const coinLogo")[0]
    used = set(re.findall(r'\[/[^\]]*?/, "([a-z0-9]+)"\]', rules))
    assert used
    assert used <= _declared()


def test_the_pack_publishes_its_logos() -> None:
    public = PACK.contribution()["public"]
    assert ["twint", "twint"] in public["merchant_logos"]
    assert public["institution_logos"]["bcf"] == "bcf"


def test_logos_are_self_contained_svgs() -> None:
    for p in LOGOS.rglob("*.svg"):
        s = p.read_text()
        assert s.lstrip().startswith("<svg"), p.name
        assert not re.search(r"(?:href|src)=\"(?!#)", s), p.name  # aucune ressource externe
        assert "<script" not in s, p.name
        assert "<image" not in s, p.name
