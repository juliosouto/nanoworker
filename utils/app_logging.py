"""Logging setup: console output plus a rotating log file under ``logs/``.

The file is what the log-reading tool (``utils/log_reader.py``) queries, so the
worker can look back at what happened. Works the same on macOS, Linux and
Windows: plain files, no shell commands.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE_NAME = "nanoworker.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 6  # keeps ~35 MB of history in total

_HANDLER_MARK = "_nanoworker_file_handler"


def setup_logging(level: int = logging.INFO) -> str:
    """Attach the console and rotating file handlers to the root logger once.

    Returns the path of the log file. Safe to call more than once.
    """
    root = logging.getLogger()
    root.setLevel(level)

    if not any(type(h) is logging.StreamHandler for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console)

    path = os.path.join(LOG_DIR, LOG_FILE_NAME)
    if not any(getattr(h, _HANDLER_MARK, False) for h in root.handlers):
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
    return path
