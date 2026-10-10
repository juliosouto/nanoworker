import os
import zipfile

import pytest
from PIL import Image

import tools.archive_tools as at
import tools.file_navigation as fn
import tools.system_status as ss
from tools.archive_tools import unzip_file, zip_files
from tools.file_navigation import list_files, search_in_files
from tools.system_status import self_status


@pytest.fixture
def perm_enabled(mocker):
    # All Tier-1 file/system tools are gated via require_permission, which
    # binds get_config from database at import time.
    mocker.patch("utils.security_utils.get_config", return_value="true")


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.txt").write_text("quarterly numbers: 42")
    (tmp_path / "docs" / "note.md").write_text("# note")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG fake")
    return tmp_path


# ---------------- list_files ----------------

def test_list_files_basic(workspace, perm_enabled):
    result = list_files(str(workspace))
    assert "docs" in result
    assert "shot.png" in result
    assert "Listing of" in result


def test_list_files_recursive_pattern(workspace, perm_enabled):
    result = list_files(str(workspace), recursive=True, pattern="*.txt")
    assert "report.txt" in result
    assert "note.md" not in result
    assert "shot.png" not in result


def test_list_files_not_found(perm_enabled):
    assert "directory not found" in list_files("/no/such/dir")


def test_list_files_denied(mocker, workspace):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    assert "Access denied" in list_files(str(workspace))


# ---------------- search_in_files ----------------

def test_search_in_files_finds_match(workspace, perm_enabled):
    result = search_in_files(str(workspace), "quarterly")
    assert "report.txt" in result
    assert "42" in result


def test_search_in_files_no_match(workspace, perm_enabled):
    result = search_in_files(str(workspace), "zzz_not_present")
    assert "No matches" in result


def test_search_in_files_requires_query(workspace, perm_enabled):
    assert "query is required" in search_in_files(str(workspace), "")


# ---------------- zip / unzip ----------------

def test_zip_and_unzip_roundtrip(workspace, perm_enabled, tmp_path):
    zpath = str(tmp_path / "pack.zip")
    result = zip_files([str(workspace / "docs" / "report.txt"), str(workspace / "shot.png")], output_path=zpath)
    assert "ZIP created with 2 file(s)" in result
    assert os.path.isfile(zpath)

    dest = str(tmp_path / "extracted")
    result = unzip_file(zpath, dest_dir=dest)
    assert "Extracted 2 file(s)" in result
    assert os.path.isfile(os.path.join(dest, "report.txt"))


def test_zip_files_missing_file(perm_enabled, tmp_path):
    result = zip_files([str(tmp_path / "ghost.txt")])
    assert "were not found" in result


def test_unzip_blocks_path_traversal(perm_enabled, tmp_path):
    evil = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escaped.txt", "bad")
    result = unzip_file(evil, dest_dir=str(tmp_path / "out"))
    assert "path traversal" in result


def test_unzip_invalid_zip(perm_enabled, tmp_path):
    bogus = str(tmp_path / "bogus.zip")
    bogus and open(bogus, "w").write("not a zip")
    result = unzip_file(bogus)
    assert "not a valid ZIP" in result


# ---------------- self_status ----------------

def test_self_status_reports_disk_and_db(perm_enabled):
    result = self_status()
    assert "Platform:" in result
    assert "Disk" in result
    assert "free" in result


def test_self_status_denied(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="false")
    assert "Access denied" in self_status()