from typing import Optional

from utils.log_reader import (
    DEFAULT_LIMIT,
    LogQuery,
    describe_query,
    parse_clock,
    parse_day,
    parse_level,
    render_entry,
    search,
    summarize,
)
from utils.security_utils import require_permission


def _build_query(date, date_to, time_from, time_to, level, min_level, contains, logger_name) -> LogQuery:
    q = LogQuery()
    if date:
        q.day = parse_day(date)
    if date_to:
        q.day_to = parse_day(date_to)
    if time_from:
        q.time_from = parse_clock(time_from)
    if time_to:
        q.time_to = parse_clock(time_to)
    if level:
        q.level = parse_level(level)
    if min_level:
        q.min_level = parse_level(min_level)
    if contains:
        q.contains = contains.strip()
    if logger_name:
        q.logger = logger_name.strip()
    return q


@require_permission('PERM_SYSTEM_DATA')
def read_logs(
    date: Optional[str] = None,
    date_to: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    level: Optional[str] = None,
    min_level: Optional[str] = None,
    contains: Optional[str] = None,
    logger_name: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    newest_first: bool = True,
) -> str:
    """
    Reads the NanoWorker application log with filters. Always use filters: returns at most `limit` entries
    (max 100) and reports how many matched in total. Use it to find out what happened, e.g. errors of a
    given day, warnings between two hours, or lines mentioning a model or a message.

    Args:
        date (str): Day to read, as YYYY-MM-DD (also accepts 'hoje' or 'ontem'). Omit to search all stored history.
        date_to (str): Last day of a range, inclusive (same formats as date).
        time_from (str): Start of the time window, HH:MM or HH:MM:SS. Applies to every day in scope.
        time_to (str): End of the time window, HH:MM or HH:MM:SS. A window like 22:00 to 02:00 crosses midnight.
        level (str): Exact level: DEBUG, INFO, WARNING, ERROR or CRITICAL.
        min_level (str): Level and above, e.g. WARNING returns WARNING, ERROR and CRITICAL.
        contains (str): Text that must appear in the message (case-insensitive), e.g. 'openrouter' or 'finish_reason'.
        logger_name (str): Part of the logger name (case-insensitive), e.g. 'llm_router' or 'sweeper'.
        limit (int): How many entries to return, 1 to 100. Default 30.
        newest_first (bool): True returns the most recent entries first (default). False returns the oldest first.

    Returns:
        str: The matching log lines, or an error message.
    """
    try:
        query = _build_query(date, date_to, time_from, time_to, level, min_level, contains, logger_name)
        entries, total = search(query, limit=limit, newest_first=newest_first)
    except ValueError as e:
        return f"Erro: {e}"
    except Exception as e:
        return f"Erro ao ler os logs: {e}"

    header = f"{total} registro(s) encontrado(s) ({describe_query(query)}); mostrando {len(entries)}."
    if not entries:
        return header + "\nNenhum registro com esses filtros."
    if total > len(entries):
        header += " Restrinja os filtros (data, hora, nível ou texto) para ver o resto."
    return header + "\n" + "\n".join(render_entry(e) for e in entries)


@require_permission('PERM_SYSTEM_DATA')
def log_summary(
    date: Optional[str] = None,
    date_to: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    contains: Optional[str] = None,
    logger_name: Optional[str] = None,
) -> str:
    """
    Summarizes the NanoWorker application log for a period: how many entries per level, the first and last
    timestamps, and the most frequent warnings and errors. Use it first to get an overview of a day or
    window, then call read_logs to see the details.

    Args:
        date (str): Day to summarize, as YYYY-MM-DD (also accepts 'hoje' or 'ontem'). Omit for all stored history.
        date_to (str): Last day of a range, inclusive.
        time_from (str): Start of the time window, HH:MM or HH:MM:SS.
        time_to (str): End of the time window, HH:MM or HH:MM:SS.
        contains (str): Only count messages containing this text (case-insensitive).
        logger_name (str): Only count loggers whose name contains this text (case-insensitive).

    Returns:
        str: The summary, or an error message.
    """
    try:
        query = _build_query(date, date_to, time_from, time_to, None, None, contains, logger_name)
        s = summarize(query)
    except ValueError as e:
        return f"Erro: {e}"
    except Exception as e:
        return f"Erro ao ler os logs: {e}"

    if s["total"] == 0:
        return f"Nenhum registro ({describe_query(query)})."
    levels = ", ".join(f"{k}={v}" for k, v in sorted(s["levels"].items()))
    lines = [
        f"{s['total']} registro(s) ({describe_query(query)}).",
        f"Período: {s['first']:%Y-%m-%d %H:%M:%S} até {s['last']:%Y-%m-%d %H:%M:%S}.",
        f"Por nível: {levels}.",
    ]
    if s["top_problems"]:
        lines.append("Problemas mais frequentes:")
        lines += [f"- ({n}x) {text}" for text, n in s["top_problems"]]
    else:
        lines.append("Nenhum WARNING ou ERROR no período.")
    return "\n".join(lines)
