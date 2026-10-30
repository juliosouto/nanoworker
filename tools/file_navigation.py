import fnmatch
import os

from utils.security_utils import require_permission

# Vendor/infra folders that pollute listings and recurse forever
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".store", ".pytest_cache", ".ruff_cache", ".whatsapp_session",
}


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


@require_permission('PERM_FS')
def list_files(path: str = ".", recursive: bool = False, pattern: str = None) -> str:
    """
    Lists files and folders inside a directory, with sizes.
    Use this tool to explore the filesystem before reading files, or to check which files exist
    (e.g. the folder where browser_screenshot or download_file_from_url saved their outputs).
    
    Args:
        path: ABSOLUTE path of the directory to list.
        recursive: If True, includes subdirectories (up to 4 levels deep, max 300 entries).
        pattern: Optional glob filter for file names, e.g. '*.png' or 'report*'.
    
    Returns:
        str: A listing of entries (sizes for files, '[dir]' for folders), or an error message.
    """
    try:
        if not path or not os.path.isdir(path):
            return f"Error: directory not found: {path}"

        max_entries = 300
        lines = []
        count = 0
        truncated = False

        if recursive:
            base_depth = path.rstrip(os.sep).count(os.sep)
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
                if root.rstrip(os.sep).count(os.sep) - base_depth >= 4:
                    dirs[:] = []
                for name in sorted(files):
                    if count >= max_entries:
                        truncated = True
                        break
                    if pattern and not fnmatch.fnmatch(name.lower(), pattern.lower()):
                        continue
                    full = os.path.join(root, name)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    lines.append(f"{_human_size(size):>9}  {full}")
                    count += 1
                if truncated:
                    break
        else:
            for name in sorted(os.listdir(path)):
                if name.startswith("."):
                    continue
                if count >= max_entries:
                    truncated = True
                    break
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    lines.append(f"{'[dir]':>9}  {full}{os.sep}")
                    count += 1
                elif not pattern or fnmatch.fnmatch(name.lower(), pattern.lower()):
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    lines.append(f"{_human_size(size):>9}  {full}")
                    count += 1

        if not lines:
            return f"No entries found in {path}" + (f" matching '{pattern}'" if pattern else "")

        header = (
            f"Listing of {path}"
            + (f" (pattern: {pattern})" if pattern else "")
            + f" - {count} entr{'y' if count == 1 else 'ies'}"
            + (" [TRUNCATED]" if truncated else "")
            + ":"
        )
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {str(e)}"


@require_permission('PERM_FS')
def search_in_files(directory: str, query: str, file_pattern: str = "*") -> str:
    """
    Searches for a text query inside the files of a directory (recursive, up to 4 levels deep).
    Use this tool to find where something is defined or mentioned across files (works like a grep).
    Skips binary/large files (>1MB) and vendor folders (.git, node_modules, __pycache__, .venv).
    
    Args:
        directory: ABSOLUTE path of the directory to search in.
        query: The text to search for (case-insensitive).
        file_pattern: Optional glob to restrict which files are searched, e.g. '*.py' (default: all files).
    
    Returns:
        str: Matching lines in 'path:line: content' format (max 40 matches), or a message saying nothing was found.
    """
    try:
        if not directory or not os.path.isdir(directory):
            return f"Error: directory not found: {directory}"
        if not query:
            return "Error: query is required."

        q = query.lower()
        max_matches = 40
        matches = []
        truncated = False
        base_depth = directory.rstrip(os.sep).count(os.sep)

        for root, dirs, files in os.walk(directory):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith("."))
            if root.rstrip(os.sep).count(os.sep) - base_depth >= 4:
                dirs[:] = []
                continue
            for name in sorted(files):
                if len(matches) >= max_matches:
                    truncated = True
                    break
                if file_pattern != "*" and not fnmatch.fnmatch(name.lower(), file_pattern.lower()):
                    continue
                full = os.path.join(root, name)
                try:
                    if os.path.getsize(full) > 1_000_000:
                        continue
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if q in line.lower():
                                matches.append(f"{full}:{i}: {line.strip()[:200]}")
                                if len(matches) >= max_matches:
                                    break
                except OSError:
                    continue
            if len(matches) >= max_matches:
                truncated = True
                break

        if not matches:
            return f"No matches for '{query}' in {directory}"

        out = f"{'[TRUNCATED] ' if truncated else ''}{len(matches)} match(es) for '{query}':\n" + "\n".join(matches)
        return out
    except Exception as e:
        return f"Error searching files: {str(e)}"