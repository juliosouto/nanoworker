import logging
import os
from datetime import date, time
from logging.handlers import RotatingFileHandler

import pytest

import utils.log_reader as lr
from utils import app_logging
from utils.log_reader import LogQuery, search, summarize

SAMPLE = """2026-11-12 08:00:00,000 | CRITICAL | app | desligando | com pipe
2026-11-13 09:00:00,001 | INFO     | agent.llm_router | Chamando modelo qwen
2026-11-13 09:00:05,500 | WARNING  | agent.lc.runner | finish_reason=length no dots
2026-11-13 10:15:00,000 | ERROR    | routes.webhooks | Falha ao enviar
Traceback (most recent call last):
  File "x.py", line 1, in <module>
RuntimeError: boom
2026-11-13 23:30:00,000 | INFO     | sweeper | tarefa agendada
"""


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "LOG_DIR", str(tmp_path))
    (tmp_path / "nanoworker.log").write_text(SAMPLE, encoding="utf-8")
    return tmp_path


def test_parses_entries_and_traceback_continuation(logdir):
    entries, total = search(LogQuery(), limit=100, newest_first=False)
    assert total == 5
    err = [e for e in entries if e.level == "ERROR"][0]
    assert err.logger == "routes.webhooks"
    assert "RuntimeError: boom" in err.message
    assert entries[0].message == "desligando | com pipe"


def test_filter_by_day_and_time_window(logdir):
    entries, total = search(LogQuery(day=date(2026, 11, 13), time_from=time(9), time_to=time(10, 30)))
    assert total == 3  # 09:00 INFO, 09:00:05 WARNING, 10:15 ERROR
    assert [e.level for e in entries] == ["ERROR", "WARNING", "INFO"]


def test_time_window_crossing_midnight(logdir):
    _, total = search(LogQuery(time_from=time(23), time_to=time(1)))
    assert total == 1


def test_level_and_min_level(logdir):
    _, exact = search(LogQuery(level="ERROR"))
    _, minimum = search(LogQuery(min_level="WARNING"))
    assert exact == 1
    assert minimum == 3  # WARNING, ERROR, CRITICAL


def test_contains_and_logger_are_case_insensitive(logdir):
    _, t1 = search(LogQuery(contains="FINISH_REASON"))
    _, t2 = search(LogQuery(logger="LLM_ROUTER"))
    assert (t1, t2) == (1, 1)


def test_day_range_inclusive(logdir):
    _, total = search(LogQuery(day_from=date(2026, 11, 12), day_to=date(2026, 11, 13)))
    assert total == 5


def test_limit_and_order(logdir):
    newest, total = search(LogQuery(), limit=2, newest_first=True)
    assert total == 5 and len(newest) == 2
    assert newest[0].ts > newest[1].ts
    oldest, _ = search(LogQuery(), limit=2, newest_first=False)
    assert oldest[0].ts < oldest[1].ts


def test_limit_is_capped(logdir):
    entries, _ = search(LogQuery(), limit=10_000)
    assert len(entries) == 5


def test_reads_rotated_backups_in_order(logdir):
    (logdir / "nanoworker.log.1").write_text(
        "2026-11-11 07:00:00,000 | ERROR    | old | antigo\n", encoding="utf-8"
    )
    entries, total = search(LogQuery(), limit=100, newest_first=False)
    assert total == 6
    assert entries[0].message == "antigo"


def test_summary_counts_and_top_problems(logdir):
    s = summarize(LogQuery(day=date(2026, 11, 13)))
    assert s["total"] == 4
    assert s["levels"] == {"INFO": 2, "WARNING": 1, "ERROR": 1}
    assert s["top_problems"][0][1] == 1


def test_bad_inputs_raise_value_error():
    from utils.log_reader import parse_clock, parse_day, parse_level

    assert parse_day("2026-11-13") == date(2026, 11, 13)
    assert parse_day("13/11/2026") == date(2026, 11, 13)
    assert parse_clock("09:05") == time(9, 5)
    assert parse_level("warn") == "WARNING"
    for bad in (lambda: parse_day("ontem-ish"), lambda: parse_clock("25h"), lambda: parse_level("VERBOSE")):
        with pytest.raises(ValueError):
            bad()


def test_tool_functions_return_text(logdir, monkeypatch):
    from tools import log_tools

    monkeypatch.setattr("utils.security_utils.get_config", lambda *a, **k: "true")
    out = log_tools.read_logs(date="2026-11-13", level="ERROR")
    assert "1 registro(s) encontrado(s)" in out
    assert "Falha ao enviar" in out
    assert log_tools.read_logs(date="2026-13-99").startswith("Erro:")
    assert "Período" in log_tools.log_summary(date="2026-11-13")


def test_setup_logging_writes_file_once(tmp_path, monkeypatch):
    monkeypatch.setattr(app_logging, "LOG_DIR", str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    for h in list(root.handlers):
        if getattr(h, app_logging._HANDLER_MARK, False):
            root.removeHandler(h)
    try:
        app_logging.setup_logging()
        app_logging.setup_logging()
        marked = [h for h in root.handlers if getattr(h, app_logging._HANDLER_MARK, False)]
        assert len(marked) == 1
        logging.getLogger("teste").warning("linha de teste")
        for h in marked:
            h.flush()
        text = (tmp_path / "nanoworker.log").read_text(encoding="utf-8")
        assert "WARNING  | teste | linha de teste" in text
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
        for h in before:
            if h not in root.handlers:
                root.addHandler(h)
