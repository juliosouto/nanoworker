"""prepare_image_for_whatsapp: what reaches WhatsApp as a photo must be one."""

import pytest
from PIL import Image

from utils.file_utils import prepare_image_for_whatsapp


def _img(path, fmt):
    Image.new("RGBA" if fmt == "WEBP" else "RGB", (4, 4), "red").save(path, fmt)
    return str(path)


def test_jpeg_and_png_pass_unchanged(tmp_path):
    assert prepare_image_for_whatsapp(_img(tmp_path / "a.jpg", "JPEG"), "image/jpeg")[1] == "image/jpeg"
    # A PNG named .jpg gets its real type.
    assert prepare_image_for_whatsapp(_img(tmp_path / "b.jpg", "PNG"), "image/jpeg")[1] == "image/png"


def test_webp_is_converted_to_jpeg(tmp_path):
    path = _img(tmp_path / "c.jpg", "WEBP")
    assert prepare_image_for_whatsapp(path, "image/jpeg") == (path, "image/jpeg")
    with Image.open(path) as img:
        assert img.format == "JPEG"


def test_html_saved_as_jpg_is_refused(tmp_path):
    path = tmp_path / "d.jpg"
    path.write_text("<!DOCTYPE html><html>403 Forbidden</html>")
    with pytest.raises(ValueError, match="web page"):
        prepare_image_for_whatsapp(str(path), "image/jpeg")


def test_image_without_extension_is_sent_as_image(tmp_path):
    path = _img(tmp_path / "download", "JPEG")
    assert prepare_image_for_whatsapp(path, "application/octet-stream")[1] == "image/jpeg"


def test_other_documents_pass_through(tmp_path):
    path = tmp_path / "e.bin"
    path.write_bytes(b"\x00\x01binary")
    assert prepare_image_for_whatsapp(str(path), "application/octet-stream") == (str(path), "application/octet-stream")
