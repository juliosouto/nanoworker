import os

import pytest
from PIL import Image

from tools.image_tools import image_info, image_resize


@pytest.fixture
def sample_png(tmp_path):
    path = str(tmp_path / "pic.png")
    Image.new("RGB", (200, 100), color=(10, 20, 30)).save(path, format="PNG")
    return path


@pytest.fixture
def perm_enabled(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="true")


def test_image_info(sample_png, perm_enabled):
    result = image_info(sample_png)
    assert "200x100 pixels" in result
    assert "PNG" in result
    assert "108 bytes" in result or "bytes" in result


def test_image_info_not_found(perm_enabled):
    assert "image file not found" in image_info("/no/img.png")


def test_image_info_not_an_image(tmp_path, perm_enabled):
    bogus = str(tmp_path / "x.png")
    open(bogus, "w").write("nope")
    assert "Error reading image info" in image_info(bogus)


def test_image_resize_width_only_keeps_aspect(sample_png, perm_enabled, tmp_path):
    out = str(tmp_path / "small.png")
    result = image_resize(sample_png, width=100, output_path=out)
    assert "100x50" in result
    with Image.open(out) as img:
        assert img.size == (100, 50)


def test_image_resize_exact(sample_png, perm_enabled, tmp_path):
    out = str(tmp_path / "exact.png")
    image_resize(sample_png, width=40, height=40, output_path=out)
    with Image.open(out) as img:
        assert img.size == (40, 40)


def test_image_resize_requires_dimensions(sample_png, perm_enabled):
    assert "provide 'width' and/or 'height'" in image_resize(sample_png)


def test_image_resize_missing_file(perm_enabled):
    assert "image file not found" in image_resize("/no/img.png", width=10)


def test_image_resize_denied(mocker, sample_png):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    assert "Access denied" in image_resize(sample_png, width=10)