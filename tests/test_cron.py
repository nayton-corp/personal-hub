from datetime import datetime

import pytest

from hub.platform.cron import missed, parse, tick

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


def test_missed_jobs_are_replayed_once_at_most_a_day_back() -> None:
    jobs = parse(CRONTAB)
    # arrêt de 02:00 à 03:05 (le tour de 03:05 lui-même n'est pas compris)
    found = missed(jobs, datetime(2026, 10, 27, 2, 0), datetime(2026, 10, 27, 3, 5))
    assert [j.command[1] for j in found] == ["verify", "backup", "nightly"]
    # trois jours d'arrêt : un seul tour de chaque, celui des dernières 24 heures
    found = missed(jobs, datetime(2026, 10, 24, 2, 0), datetime(2026, 10, 27, 3, 5))
    assert [j.command[-1] for j in found] == ["jours ouvrés", "verify", "backup", "nightly"]
    assert missed(jobs, datetime(2026, 10, 27, 3, 1), datetime(2026, 10, 27, 3, 5)) == []


@pytest.mark.parametrize("bad", ["* * * * hub", "61 * * * * x", "*/0 * * * * x", "5-1 * * * * x"])
def test_parse_rejects(bad: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        parse(bad)


def test_repository_crontab_is_valid() -> None:
    from pathlib import Path

    jobs = parse((Path(__file__).parents[1] / "deploy" / "crontab").read_text())
    assert {j.command[1] for j in jobs} >= {"verify", "backup", "nightly"}


def test_a_failing_job_is_reported_and_a_reported_one_is_not_repeated() -> None:
    from hub.platform.cron import REPORTED

    seen: list[tuple[tuple[str, ...], int]] = []
    codes = {"verify": REPORTED, "backup": 1, "nightly": 0}
    jobs = parse("0 3 * * * hub verify\n0 3 * * * hub backup\n0 3 * * * hub nightly\n")
    results = tick(
        jobs,
        datetime(2026, 10, 27, 3, 0),
        lambda cmd: codes[cmd[1]],
        lambda cmd, code: seen.append((cmd, code)),
    )
    assert [code for _line, code in results] == [REPORTED, 1, 0]
    assert seen == [(("hub", "backup"), 1)]  # verify a déjà prévenu lui-même, nightly a réussi


def test_an_alert_that_fails_does_not_stop_the_scheduler() -> None:
    def broken(_cmd: tuple[str, ...], _code: int) -> None:
        raise OSError

    jobs = parse("0 3 * * * hub backup\n0 3 * * * hub nightly\n")
    results = tick(jobs, datetime(2026, 10, 27, 3, 0), lambda _cmd: 1, broken)
    assert len(results) == 2


def test_a_missing_command_is_a_failure_not_a_crash() -> None:
    from hub.platform.cron import NOT_FOUND, _run

    assert _run(("commande-qui-n-existe-pas",)) == NOT_FOUND
