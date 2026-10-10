import os
import platform
import shutil

from utils.security_utils import require_permission

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dir_size(path: str, max_files: int = 3000) -> int:
    total = 0
    counted = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                counted += 1
            except OSError:
                pass
            if counted >= max_files:
                return total
    return total


@require_permission('PERM_SYSTEM_DATA')
def self_status() -> str:
    """
    Returns a health report of this machine: free disk space, database size, workspace size and platform info.
    Use this tool to self-diagnose problems (e.g. 'quota exceeded', failed saves) by checking whether the disk
    is almost full or the database/workspace grew too much.
    
    Returns:
        str: A human-readable status report, or an error message.
    """
    try:
        lines = [f"Platform: {platform.system()} {platform.release()} | Python {platform.python_version()}"]

        usage = shutil.disk_usage(_PROJECT_ROOT)
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        lines.append(f"Disk ({_PROJECT_ROOT}): {free_gb:.1f} GB free of {total_gb:.1f} GB")
        if free_gb < 1.0:
            lines.append("⚠️ WARNING: less than 1 GB free — saves and downloads may fail.")

        db_path = os.path.join(_PROJECT_ROOT, "nanoworker.db")
        if os.path.isfile(db_path):
            lines.append(f"Database (nanoworker.db): {os.path.getsize(db_path)} bytes")

        files_dir = os.path.join(_PROJECT_ROOT, "files")
        if os.path.isdir(files_dir):
            lines.append(f"Workspace (files/): {_dir_size(files_dir)} bytes")

        return "\n".join(lines)
    except Exception as e:
        return f"Error collecting system status: {str(e)}"