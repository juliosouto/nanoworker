import logging
import os

from PIL import Image

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission

logger = logging.getLogger(__name__)


@require_permission('PERM_FS')
def crop_image(image_path: str, left: int, top: int, right: int, bottom: int, output_path: str = None) -> str:
    """
    Crops a local image file to the region defined by pixel coordinates and saves a new PNG file.
    Use this tool to cut out a specific area of an image or screenshot (e.g. after browser_screenshot
    or download_file_from_url). Coordinates are PIXELS measured from the top-left corner of the image:
    left/top are the upper-left corner of the crop and right/bottom are the lower-right corner.
    Out-of-range values are clamped to the image bounds.
    
    Args:
        image_path: ABSOLUTE path of the source image (exactly as returned by other tools, e.g. browser_screenshot).
        left: X pixel of the upper-left corner (>= 0).
        top: Y pixel of the upper-left corner (>= 0).
        right: X pixel of the lower-right corner (must be greater than left).
        bottom: Y pixel of the lower-right corner (must be greater than top).
        output_path: Optional ABSOLUTE path for the cropped PNG. If omitted, a new temp file is created.
        
    Returns:
        str: A success message containing the ABSOLUTE path of the cropped PNG, or an error message.
             On invalid coordinates the error includes the source image dimensions so you can fix them.
             IMPORTANT: to share the cropped image afterwards, you MUST pass the exact absolute path returned
             here to the send_whatsapp_file tool — do not reconstruct it.
    """
    try:
        if not image_path or not os.path.isfile(image_path):
            return f"Error: image file not found: {image_path}"

        try:
            left = int(left)
            top = int(top)
            right = int(right)
            bottom = int(bottom)
        except (TypeError, ValueError):
            return (
                f"Error: coordinates must be integer numbers (pixels). "
                f"Got left={left!r}, top={top!r}, right={right!r}, bottom={bottom!r}."
            )

        with Image.open(image_path) as img:
            width, height = img.size

            if left < 0 or top < 0:
                return (
                    f"Error: 'left' and 'top' must be >= 0. "
                    f"The image is {width}x{height} pixels (width x height)."
                )

            # Clamp to image bounds instead of failing — e.g. right=5000 on a
            # 1920px-wide image simply crops to the right edge.
            clamped = (max(0, left), max(0, top), min(right, width), min(bottom, height))

            if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
                return (
                    f"Error: empty crop region. 'right' must be greater than 'left' and "
                    f"'bottom' greater than 'top'. The image is {width}x{height} pixels "
                    f"(width x height); your coordinates produced the empty box {clamped}."
                )

            cropped = img.crop(clamped)

            if output_path:
                out = output_path
                parent = os.path.dirname(os.path.abspath(out))
                os.makedirs(parent, exist_ok=True)
            else:
                base = os.path.splitext(os.path.basename(image_path))[0]
                out = get_temp_file_path(f"{base}_cropped.png")

            cropped.save(out, format="PNG")

        if clamped != (left, top, right, bottom):
            note = f" (coordinates were clamped to the image bounds: {clamped})"
        else:
            note = ""

        return (
            f"Image cropped successfully: box (left={clamped[0]}, top={clamped[1]}, "
            f"right={clamped[2]}, bottom={clamped[3]}) = {clamped[2] - clamped[0]}x{clamped[3] - clamped[1]} pixels"
            f"{note}. Saved to {out}"
        )

    except Exception as e:
        logger.error(f"crop_image failed: {e}")
        return f"Error cropping image: {str(e)}"


@require_permission('PERM_FS')
def crop_image(image_path: str, left: int, top: int, right: int, bottom: int, output_path: str = None) -> str:
    """
    Crops a local image file to the region defined by pixel coordinates and saves a new PNG file.
    Use this tool to cut out a specific area of an image or screenshot (e.g. after browser_screenshot
    or download_file_from_url). Coordinates are PIXELS measured from the top-left corner of the image:
    left/top are the upper-left corner of the crop and right/bottom are the lower-right corner.
    Out-of-range values are clamped to the image bounds.
    
    Args:
        image_path: ABSOLUTE path of the source image (exactly as returned by other tools, e.g. browser_screenshot).
        left: X pixel of the upper-left corner (>= 0).
        top: Y pixel of the upper-left corner (>= 0).
        right: X pixel of the lower-right corner (must be greater than left).
        bottom: Y pixel of the lower-right corner (must be greater than top).
        output_path: Optional ABSOLUTE path for the cropped PNG. If omitted, a new temp file is created.
        
    Returns:
        str: A success message containing the ABSOLUTE path of the cropped PNG, or an error message.
             On invalid coordinates the error includes the source image dimensions so you can fix them.
             IMPORTANT: to share the cropped image afterwards, you MUST pass the exact absolute path returned
             here to the send_whatsapp_file tool — do not reconstruct it.
    """
    try:
        if not image_path or not os.path.isfile(image_path):
            return f"Error: image file not found: {image_path}"

        try:
            left = int(left)
            top = int(top)
            right = int(right)
            bottom = int(bottom)
        except (TypeError, ValueError):
            return (
                f"Error: coordinates must be integer numbers (pixels). "
                f"Got left={left!r}, top={top!r}, right={right!r}, bottom={bottom!r}."
            )

        with Image.open(image_path) as img:
            width, height = img.size

            if left < 0 or top < 0:
                return (
                    f"Error: 'left' and 'top' must be >= 0. "
                    f"The image is {width}x{height} pixels (width x height)."
                )

            # Clamp to image bounds instead of failing — e.g. right=5000 on a
            # 1920px-wide image simply crops to the right edge.
            clamped = (max(0, left), max(0, top), min(right, width), min(bottom, height))

            if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
                return (
                    f"Error: empty crop region. 'right' must be greater than 'left' and "
                    f"'bottom' greater than 'top'. The image is {width}x{height} pixels "
                    f"(width x height); your coordinates produced the empty box {clamped}."
                )

            cropped = img.crop(clamped)

            if output_path:
                out = output_path
                parent = os.path.dirname(os.path.abspath(out))
                os.makedirs(parent, exist_ok=True)
            else:
                base = os.path.splitext(os.path.basename(image_path))[0]
                out = get_temp_file_path(f"{base}_cropped.png")

            cropped.save(out, format="PNG")

        if clamped != (left, top, right, bottom):
            note = f" (coordinates were clamped to the image bounds: {clamped})"
        else:
            note = ""

        return (
            f"Image cropped successfully: box (left={clamped[0]}, top={clamped[1]}, "
            f"right={clamped[2]}, bottom={clamped[3]}) = {clamped[2] - clamped[0]}x{clamped[3] - clamped[1]} pixels"
            f"{note}. Saved to {out}"
        )

    except Exception as e:
        logger.error(f"crop_image failed: {e}")
        return f"Error cropping image: {str(e)}"