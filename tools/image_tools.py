import os

from PIL import Image

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission


@require_permission('PERM_FS')
def image_info(image_path: str) -> str:
    """
    Returns metadata of a local image file: dimensions, format, color mode, file size and EXIF info when available.
    Use this tool before or after editing images to know their exact pixel size (e.g. to plan crop_image coordinates).
    
    Args:
        image_path: ABSOLUTE path of the image file.
    
    Returns:
        str: A message with the image metadata, or an error message.
    """
    try:
        if not image_path or not os.path.isfile(image_path):
            return f"Error: image file not found: {image_path}"

        size_bytes = os.path.getsize(image_path)

        with Image.open(image_path) as img:
            width, height = img.size
            fmt = img.format or "unknown"
            mode = img.mode

            exif_parts = []
            try:
                exif = img.getexif()
                if exif:
                    from PIL.ExifTags import TAGS
                    for tag_id, value in list(exif.items())[:8]:
                        name = TAGS.get(tag_id, str(tag_id))
                        exif_parts.append(f"{name}={str(value)[:60]}")
            except Exception:
                pass

        lines = [
            f"Image: {image_path}",
            f"Dimensions: {width}x{height} pixels (width x height)",
            f"Format: {fmt} | Mode: {mode} | File size: {size_bytes} bytes",
        ]
        if exif_parts:
            lines.append("EXIF: " + "; ".join(exif_parts))
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading image info: {str(e)}"


@require_permission('PERM_FS')
def image_resize(image_path: str, width: int = None, height: int = None, output_path: str = None) -> str:
    """
    Resizes a local image and saves a new file. If only one dimension is given, the other is scaled proportionally.
    Use this tool to shrink large images (e.g. to fit WhatsApp limits) or to standardize screenshot sizes.
    
    Args:
        image_path: ABSOLUTE path of the source image.
        width: Target width in pixels. If height is omitted, height is scaled to keep the aspect ratio.
        height: Target height in pixels. If width is omitted, width is scaled to keep the aspect ratio.
        output_path: Optional ABSOLUTE path for the resized image. If omitted, a new temp file is created.
    
    Returns:
        str: A success message containing the ABSOLUTE path of the resized image, or an error message.
    """
    try:
        if not image_path or not os.path.isfile(image_path):
            return f"Error: image file not found: {image_path}"

        if width is None and height is None:
            return "Error: provide 'width' and/or 'height' in pixels."

        try:
            width = int(width) if width is not None else None
            height = int(height) if height is not None else None
        except (TypeError, ValueError):
            return f"Error: width/height must be integer numbers. Got width={width!r}, height={height!r}."

        with Image.open(image_path) as img:
            orig_w, orig_h = img.size
            if width and height:
                new_size = (width, height)
            elif width:
                new_size = (width, max(1, round(orig_h * width / orig_w)))
            else:
                new_size = (max(1, round(orig_w * height / orig_h)), height)

            resized = img.resize(new_size)

            if output_path:
                out = output_path
                parent = os.path.dirname(os.path.abspath(out))
                os.makedirs(parent, exist_ok=True)
            else:
                base = os.path.splitext(os.path.basename(image_path))[0]
                out = get_temp_file_path(f"{base}_{new_size[0]}x{new_size[1]}.png")

            if out.lower().endswith((".jpg", ".jpeg")) and resized.mode in ("RGBA", "P"):
                resized = resized.convert("RGB")
            resized.save(out)

        return (
            f"Image resized from {orig_w}x{orig_h} to {new_size[0]}x{new_size[1]} pixels. "
            f"Saved to {out}"
        )
    except Exception as e:
        return f"Error resizing image: {str(e)}"