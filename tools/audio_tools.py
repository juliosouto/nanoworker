import os
import shutil
import subprocess

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission

_ALLOWED_FORMATS = ("mp3", "ogg", "wav", "m4a", "aac", "flac")


def _run_ffmpeg(args: list) -> str:
    if shutil.which("ffmpeg") is None:
        return "Error: the 'ffmpeg' binary is not available in this environment."

    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error"] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")[-400:]
        return f"Error: ffmpeg failed ({err})"
    return ""


@require_permission('PERM_FS')
def audio_convert(input_path: str, output_format: str = "mp3", output_path: str = None) -> str:
    """
    Converts a local audio file to another format using ffmpeg.
    Use this tool to convert voice notes or downloaded audio (e.g. ogg to mp3) so they can be shared or processed.
    
    Args:
        input_path: ABSOLUTE path of the source audio file.
        output_format: Target format without dot. One of: mp3, ogg, wav, m4a, aac, flac (default mp3).
        output_path: Optional ABSOLUTE path for the converted file. If omitted, a new temp file is created.
    
    Returns:
        str: A success message containing the ABSOLUTE path of the converted file, or an error message.
    """
    try:
        if not input_path or not os.path.isfile(input_path):
            return f"Error: audio file not found: {input_path}"

        output_format = (output_format or "mp3").lower().lstrip(".")
        if output_format not in _ALLOWED_FORMATS:
            return f"Error: output_format must be one of: {', '.join(_ALLOWED_FORMATS)}."

        if output_path:
            out = output_path
            parent = os.path.dirname(os.path.abspath(out))
            os.makedirs(parent, exist_ok=True)
        else:
            base = os.path.splitext(os.path.basename(input_path))[0]
            out = get_temp_file_path(f"{base}.{output_format}")

        error = _run_ffmpeg(["-i", input_path, out])
        if error:
            return error

        size = os.path.getsize(out)
        return f"Audio converted to {output_format} ({size} bytes). Saved to {out}"
    except Exception as e:
        return f"Error converting audio: {str(e)}"


@require_permission('PERM_FS')
def audio_trim(input_path: str, start_seconds: float, end_seconds: float, output_path: str = None) -> str:
    """
    Cuts a segment out of a local audio file using ffmpeg.
    Use this tool to extract part of a voice note or audio (e.g. from second 10 to second 25).
    
    Args:
        input_path: ABSOLUTE path of the source audio file.
        start_seconds: Start of the segment in seconds (>= 0).
        end_seconds: End of the segment in seconds (must be greater than start_seconds).
        output_path: Optional ABSOLUTE path for the trimmed file. If omitted, a new temp file is created
                     in the same format as the source.
    
    Returns:
        str: A success message containing the ABSOLUTE path of the trimmed file, or an error message.
    """
    try:
        if not input_path or not os.path.isfile(input_path):
            return f"Error: audio file not found: {input_path}"

        try:
            start_seconds = float(start_seconds)
            end_seconds = float(end_seconds)
        except (TypeError, ValueError):
            return f"Error: start_seconds/end_seconds must be numbers. Got {start_seconds!r} and {end_seconds!r}."

        if start_seconds < 0 or end_seconds <= start_seconds:
            return (
                f"Error: start_seconds must be >= 0 and end_seconds must be greater than "
                f"start_seconds. Got start={start_seconds}, end={end_seconds}."
            )

        if output_path:
            out = output_path
            parent = os.path.dirname(os.path.abspath(out))
            os.makedirs(parent, exist_ok=True)
        else:
            base, ext = os.path.splitext(os.path.basename(input_path))
            out = get_temp_file_path(f"{base}_trim{ext or '.mp3'}")

        error = _run_ffmpeg(
            ["-ss", str(start_seconds), "-to", str(end_seconds), "-i", input_path, out]
        )
        if error:
            return error

        size = os.path.getsize(out)
        duration = end_seconds - start_seconds
        return f"Audio trimmed ({duration:.1f}s segment, {size} bytes). Saved to {out}"
    except Exception as e:
        return f"Error trimming audio: {str(e)}"