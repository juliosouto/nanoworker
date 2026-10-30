import os

import pytest
from PIL import Image
from unittest.mock import MagicMock

import tools.image_crop as ic
from tools.image_crop import crop_image


@pytest.fixture
def sample_image(tmp_path):
    """A 100x80 red PNG on disk."""
    path = str(tmp_path / "source.png")
    Image.new("RGB", (100, 80), color=(200, 0, 0)).save(path, format="PNG")
    return path


@pytest.fixture
def perm_enabled(mocker):
    # crop_image is gated by PERM_FS; require_permission binds get_config at
    # import time, so patch utils.security_utils.get_config.
    mocker.patch("utils.security_utils.get_config", return_value="true")


def test_crop_image_basic(sample_image, perm_enabled, tmp_path):
    out = str(tmp_path / "out.png")
    result = crop_image(sample_image, 10, 20, 60, 70, output_path=out)

    assert "cropped successfully" in result
    assert "50x50 pixels" in result
    assert os.path.isfile(out)

    with Image.open(out) as cropped:
        assert cropped.size == (50, 50)
        # Top-left pixel must still be the source red
        assert cropped.getpixel((0, 0)) == (200, 0, 0)


def test_crop_image_clamps_out_of_bounds(sample_image, perm_enabled, tmp_path):
    out = str(tmp_path / "clamped.png")
    result = crop_image(sample_image, 50, 40, 500, 500, output_path=out)

    assert "clamped" in result
    assert os.path.isfile(out)
    with Image.open(out) as cropped:
        assert cropped.size == (50, 40)  # 100-50 x 80-40


def test_crop_image_empty_region_returns_didactic_error(sample_image, perm_enabled):
    result = crop_image(sample_image, 50, 50, 50, 50)
    assert "empty crop region" in result
    assert "100x80" in result  # dimensions included so the model can fix coords


def test_crop_image_invalid_coords_type(sample_image, perm_enabled):
    result = crop_image(sample_image, "a", 0, 50, 50)
    assert "must be integer numbers" in result


def test_crop_image_negative_origin(sample_image, perm_enabled):
    result = crop_image(sample_image, -10, 0, 50, 50)
    assert "'left' and 'top' must be >= 0" in result
    assert "100x80" in result


def test_crop_image_file_not_found(perm_enabled):
    result = crop_image("/does/not/exist.png", 0, 0, 10, 10)
    assert "image file not found" in result


def test_crop_image_not_an_image(tmp_path, perm_enabled):
    bogus = str(tmp_path / "bogus.png")
    with open(bogus, "w") as f:
        f.write("this is not an image")
    result = crop_image(bogus, 0, 0, 10, 10)
    assert "Error cropping image" in result


def test_crop_image_default_output_in_temp(sample_image, perm_enabled, mocker):
    mocker.patch("tools.image_crop.get_temp_file_path", return_value="/tmp/fixed_crop.png")
    result = crop_image(sample_image, 0, 0, 10, 10)
    assert "Saved to /tmp/fixed_crop.png" in result


def test_crop_image_denied_without_permission(mocker, sample_image):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    result = crop_image(sample_image, 0, 0, 10, 10)
    assert "Access denied" in result
    assert "PERM_FS" in result


def test_crop_image_is_loaded_for_all_platforms():
    """Root tools/ modules are loaded by every platform loader, so the crop
    tool must be available regardless of the OS the agent runs on."""
    import ast

    root = os.path.join(os.path.dirname(ic.__file__))
    assert os.path.basename(root) == "tools"  # must live in tools/ root

    tree = ast.parse(open(os.path.join(root, "image_crop.py")).read())
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "crop_image" in names