import io
import json

import structlog

from hub.kernel.money import Money
from hub.platform import logging as hub_logging


def _capture() -> io.StringIO:
    buf = io.StringIO()
    hub_logging.configure("INFO", stream=buf)
    return buf


def _lines(buf: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in buf.getvalue().splitlines()]


def test_plain_event_is_json() -> None:
    buf = _capture()
    structlog.get_logger().info("import.applied", import_id="01ABC", new=3)
    (line,) = _lines(buf)
    assert line["event"] == "import.applied"
    assert line["new"] == 3
    assert line["level"] == "info"
    assert str(line["timestamp"]).endswith("Z")


def test_amount_is_rejected() -> None:
    buf = _capture()
    structlog.get_logger().info("import.applied", amount_minor=-4550)
    (line,) = _lines(buf)
    assert line["event"] == "log.rejected"
    assert line["original_event"] == "import.applied"
    assert line["rejected_keys"] == ["amount_minor"]
    assert "4550" not in buf.getvalue()


def test_money_iban_and_nested_values_are_rejected() -> None:
    buf = _capture()
    log = structlog.get_logger()
    log.info("x", value=Money(100, "CHF"))
    log.info("y", note="virement CH93 0076 2011 6238 5295 7")
    log.info("z", stats={"balance": 12})
    log.info("paiement à CH9300762011623852957")
    lines = _lines(buf)
    assert [x["event"] for x in lines] == ["log.rejected"] * 4
    assert lines[3]["original_event"] == "?"
    assert "CH93" not in buf.getvalue()
    assert "12" not in json.dumps(lines[2]["rejected_keys"])


def test_forbidden_keys_helper() -> None:
    assert hub_logging.forbidden_keys_in(["IBAN", "count"]) == {"IBAN"}
