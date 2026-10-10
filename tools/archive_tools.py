import os
import zipfile

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission


@require_permission('PERM_FS')
def zip_files(file_paths: list, output_path: str = None) -> str:
    """
    Packs multiple local files into a single ZIP archive.
    Use this tool to group several files (e.g. documents or images) into one archive before sending.
    
    Args:
        file_paths: List of ABSOLUTE paths of the files to pack (exactly as returned by other tools).
        output_path: Optional ABSOLUTE path for the .zip file. If omitted, a new temp file is created.
    
    Returns:
        str: A success message containing the ABSOLUTE path of the ZIP, or an error message.
             IMPORTANT: to share the archive afterwards, pass the exact path returned here to send_whatsapp_file.
    """
    try:
        if not file_paths or not isinstance(file_paths, list):
            return "Error: file_paths must be a list of absolute file paths."

        missing = [p for p in file_paths if not p or not os.path.isfile(p)]
        if missing:
            return f"Error: these files were not found: {', '.join(missing)}"

        if output_path:
            out = output_path
            parent = os.path.dirname(os.path.abspath(out))
            os.makedirs(parent, exist_ok=True)
        else:
            out = get_temp_file_path("archive.zip")

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in file_paths:
                zf.write(p, arcname=os.path.basename(p))

        size = os.path.getsize(out)
        return f"ZIP created with {len(file_paths)} file(s) ({size} bytes). Saved to {out}"
    except Exception as e:
        return f"Error creating ZIP: {str(e)}"


@require_permission('PERM_FS')
def unzip_file(zip_path: str, dest_dir: str = None) -> str:
    """
    Extracts a ZIP archive into a folder and lists the extracted files.
    Use this tool to unpack ZIP archives (e.g. received files) so their contents can be read with other tools.
    
    Args:
        zip_path: ABSOLUTE path of the .zip file.
        dest_dir: Optional ABSOLUTE path of the extraction folder. If omitted, a new temp folder is created.
    
    Returns:
        str: A success message with the destination folder and the extracted file names, or an error message.
    """
    try:
        if not zip_path or not os.path.isfile(zip_path):
            return f"Error: ZIP file not found: {zip_path}"

        if dest_dir:
            base_dir = dest_dir
            os.makedirs(base_dir, exist_ok=True)
        else:
            base_name = os.path.splitext(os.path.basename(zip_path))[0]
            base_dir = get_temp_file_path(base_name)
            os.makedirs(base_dir, exist_ok=True)

        extracted = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                # Zip-slip guard: refuse absolute paths and parent traversal
                target = os.path.normpath(os.path.join(base_dir, member))
                if not os.path.abspath(target).startswith(os.path.abspath(base_dir)):
                    return f"Error: refusing to extract unsafe entry '{member}' (path traversal)."
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                zf.extract(member, base_dir)
                extracted.append(member)

        if not extracted:
            return f"The archive {zip_path} is empty."

        listing = ", ".join(extracted[:20])
        extra = f" (+{len(extracted) - 20} more)" if len(extracted) > 20 else ""
        return (
            f"Extracted {len(extracted)} file(s) to {base_dir}: {listing}{extra}. "
            f"Use read_file on any of them to inspect its contents."
        )
    except zipfile.BadZipFile:
        return f"Error: {zip_path} is not a valid ZIP archive."
    except Exception as e:
        return f"Error extracting ZIP: {str(e)}"