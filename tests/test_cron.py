from datetime import datetime

import pytest

from hub.core.cron import parse, tick

CRONTAB = """
# commentaire
15 2 * * * hub verify
30 2 * * * hub backup
0 3 * * * hub nightly
*/20 8-9 * * 1-5 echo "jours ouvrés"
0 9 * * 0 echo dimanche
0 9 * * 7 echo dimanche-bis
"""


def test_parse_and_due() -> None:
    jobs = parse(CRONTAB)
    assert len(jobs) == 6
    assert jobs[3].command == ("echo", "jours ouvrés")
    at = datetime(2026, 10, 27, 2, 15)  # mardi
    assert [j.command[1] for j in jobs if j.due(at)] == ["verify"]
    assert jobs[3].due(datetime(2026, 10, 27, 8, 40))
    assert not jobs[3].due(datetime(2026, 10, 25, 8, 40))  # dimanche
    sunday = datetime(2026, 10, 25, 9, 0)
    assert jobs[4].due(sunday)
    assert jobs[5].due(sunday)


def test_tick_runs_due_jobs() -> None:
    ran: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> int:
        ran.append(cmd)
        return 0

    results = tick(parse(CRONTAB), datetime(2026, 10, 27, 3, 0), runner)
    assert ran == [("hub", "nightly")]
    assert results[0][1] == 0


@pytest.mark.parametrize("bad", ["* * * * hub", "61 * * * * x", "*/0 * * * * x", "5-1 * * * * x"])
def test_parse_rejects(bad: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        parse(bad)


def test_repository_crontab_is_valid() -> None:
    from pathlib import Path

    jobs = parse((Path(__file__).parents[1] / "deploy" / "crontab").read_text())
    assert {j.command[1] for j in jobs} >= {"verify", "backup", "nightly"}
