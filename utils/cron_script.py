"""
Runs the Python script of a cron job.

A job with a script does not call the LLM: when it is due, the script runs in
a separate Python process and its stdout is what gets sent to the chat. Empty
stdout means the job stays silent. Scripts run only while the PERM_TERMINAL
permission is on, the same gate as the bash tool, because they execute code
on the machine unattended.
"""

import logging
import os
import subprocess
import sys
import tempfile

from database import get_config

logger = logging.getLogger(__name__)

SCRIPT_TIMEOUT_SECONDS = 120
_MAX_ERROR_CHARS = 800


def run_cron_script(script: str) -> str:
    """Runs ``script`` and returns the text to send to the chat ('' to stay silent)."""
    if get_config('PERM_TERMINAL', 'false').lower() != 'true':
        return "Error: the cron script did not run because the 'PERM_TERMINAL' permission is disabled."

    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, 'job.py')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(script)
        try:
            proc = subprocess.run(
                [sys.executable, '-I', path],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=SCRIPT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"Error: the cron script timed out after {SCRIPT_TIMEOUT_SECONDS} seconds."

    if proc.returncode != 0:
        logger.warning(f"Cron script exited with {proc.returncode}: {proc.stderr[-300:]}")
        err = (proc.stderr or '').strip()[-_MAX_ERROR_CHARS:]
        return f"Error: the cron script failed (exit code {proc.returncode}).\n{err}".rstrip()
    return (proc.stdout or '').strip()
