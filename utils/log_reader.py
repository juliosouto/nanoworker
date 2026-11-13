"""Filtered reader for the NanoWorker log files written by ``utils/app_logging.py``.

Reads the current file and its rotated backups in chronological order, keeps
only the entries that match the filters and never loads the whole history into
memory: at most ``limit`` entries are held at a time.

Pure Python and path-based, so it behaves the same on macOS, Linux and Windows.
"""

import os
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Iterator, List, Optional

from utils.app_logging import LOG_DIR, LOG_FILE_NAME

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
MAX_MESSAGE_CHARS = 600

_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:,\d+)? \| (DEBUG|INFO|WARNING|ERROR|CRITICAL) +\| ([^|]*?) \| (.*)$"
)


@dataclass
class LogEntry:
    ts: datetime
    level: str
    logger: str
    message: str  # first line plus any continuation lines (tracebacks)


@dataclass
class LogQuery:
    day: Optional[date] = None
    day_from: Optional[date] = None
    day_to: Optional[date] = None
    time_from: Optional[time] = None
    time_to: Optional[time] = None
    level: Optional[str] = None  # exact level
    min_level: Optional[str] = None  # this level and above
    contains: Optional[str] = None  # case-insensitive text in the message
    logger: Optional[str] = None  # case-insensitive part of the logger name

    def matches(self, e: LogEntry) -> bool:
        d = e.ts.date()
        if self.day and d != self.day:
            return False
        if self.day_from and d < self.day_from:
            return False
        if self.day_to and d > self.day_to:
            return False
        if self.time_from or self.time_to:
            t = e.ts.time()
            lo, hi = self.time_from, self.time_to
            if lo and hi and lo > hi:  # window crosses midnight, e.g. 22:00-02:00
                if not (t >= lo or t <= hi):
                    return False
            else:
                if lo and t < lo:
                    return False
                if hi and t > hi:
                    return False
        if self.level and e.level != self.level:
            return False
        if self.min_level and LEVELS.index(e.level) < LEVELS.index(self.min_level):
            return False
        if self.contains and self.contains.lower() not in e.message.lower():
            return False
        if self.logger and self.logger.lower() not in e.logger.lower():
            return False
        return True


def parse_day(value: str) -> date:
    """Accepts YYYY-MM-DD, DD/MM/YYYY, 'today'/'hoje' and 'yesterday'/'ontem'."""
    v = value.strip().lower()
    today = datetime.now().date()
    if v in ("today", "hoje"):
        return today
    if v in ("yesterday", "ontem"):
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"data inválida '{value}' (use AAAA-MM-DD, DD/MM/AAAA, hoje ou ontem)")


def parse_clock(value: str) -> time:
    """Accepts HH:MM or HH:MM:SS."""
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except ValueError:
            pass
    raise ValueError(f"hora inválida '{value}' (use HH:MM ou HH:MM:SS)")


def parse_level(value: str) -> str:
    v = value.strip().upper()
    if v == "WARN":
        v = "WARNING"
    if v not in LEVELS:
        raise ValueError(f"nível inválido '{value}' (use {', '.join(LEVELS)})")
    return v


def log_files() -> List[str]:
    """Rotated backups (oldest first) followed by the current log file."""
    files = []
    for n in range(20, 0, -1):
        p = os.path.join(LOG_DIR, f"{LOG_FILE_NAME}.{n}")
        if os.path.isfile(p):
            files.append(p)
    current = os.path.join(LOG_DIR, LOG_FILE_NAME)
    if os.path.isfile(current):
        files.append(current)
    return files


def iter_entries(paths: List[str]) -> Iterator[LogEntry]:
    """Yields parsed entries in file order. Lines that do not start a new entry
    (tracebacks, multi-line messages) are attached to the entry before them."""
    current: Optional[LogEntry] = None
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\r\n")
                m = _LINE_RE.match(line)
                if m:
                    if current is not None:
                        yield current
                    d, t, level, logger_name, msg = m.groups()
                    current = LogEntry(
                        ts=datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S"),
                        level=level,
                        logger=logger_name.strip(),
                        message=msg,
                    )
                elif current is not None:
                    current.message += "\n" + line
    if current is not None:
        yield current


def search(query: LogQuery, limit: int = DEFAULT_LIMIT, newest_first: bool = True):
    """Returns (entries, total_matches). ``entries`` holds at most ``limit`` items,
    newest first when ``newest_first`` is True."""
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    files = log_files()
    total = 0
    if newest_first:
        kept = deque(maxlen=limit)
        for e in iter_entries(files):
            if query.matches(e):
                total += 1
                kept.append(e)
        return list(reversed(kept)), total
    kept_list: List[LogEntry] = []
    for e in iter_entries(files):
        if query.matches(e):
            total += 1
            if len(kept_list) < limit:
                kept_list.append(e)
    return kept_list, total


def summarize(query: LogQuery, top: int = 5):
    """Counts per level, first/last timestamp and the most frequent problems
    (WARNING and above) for the entries matching the query."""
    levels: Counter = Counter()
    problems: Counter = Counter()
    first = last = None
    total = 0
    for e in iter_entries(log_files()):
        if not query.matches(e):
            continue
        total += 1
        levels[e.level] += 1
        first = first or e.ts
        last = e.ts
        if LEVELS.index(e.level) >= LEVELS.index("WARNING"):
            head = e.message.split("\n", 1)[0][:120]
            problems[f"{e.level} {e.logger}: {head}"] += 1
    return {
        "total": total,
        "levels": dict(levels),
        "first": first,
        "last": last,
        "top_problems": problems.most_common(top),
    }


def render_entry(e: LogEntry) -> str:
    msg = e.message
    if len(msg) > MAX_MESSAGE_CHARS:
        msg = msg[:MAX_MESSAGE_CHARS] + " …[cortado]"
    return f"{e.ts:%Y-%m-%d %H:%M:%S} | {e.level} | {e.logger} | {msg}"


def describe_query(query: LogQuery) -> str:
    parts = []
    if query.day:
        parts.append(f"dia={query.day.isoformat()}")
    if query.day_from or query.day_to:
        parts.append(f"dias={query.day_from or '...'}..{query.day_to or '...'}")
    if query.time_from or query.time_to:
        parts.append(f"hora={query.time_from or '00:00'}..{query.time_to or '23:59'}")
    if query.level:
        parts.append(f"nível={query.level}")
    if query.min_level:
        parts.append(f"nível>={query.min_level}")
    if query.contains:
        parts.append(f"texto='{query.contains}'")
    if query.logger:
        parts.append(f"logger='{query.logger}'")
    return ", ".join(parts) or "sem filtros"
