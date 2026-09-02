"""Tests for the composite tool tools.<os>.find_and_send_image.

The tool wraps search + download + send into a single call so small models only
need to provide a query. These tests mock the three backend steps.
"""
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.macos.find_and_send_image import (
    find_and_send_image,
    _sanitize_filename_from_wikimedia_url,
)

GROUP_JID = "wa_web:120363123456789-123@g.us"


def _results(url="https://upload.wikimedia.org/wikipedia/commons/test_dog.jpg"):
    return json.dumps([{"title": "Test_Dog.jpg", "url": url}])


def test_success_chain(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel",
        lambda: GROUP_JID,
    )
    monkeypatch.setattr(
        "tools.macos.wikimedia_image_search.search_wikimedia_images",
        lambda q, limit=5: _results(),
    )
    monkeypatch.setattr(
        "tools.macos.download_file_from_url.download_file_from_url",
        lambda url, filename, category: f"/app/files/images/{filename}",
    )
    monkeypatch.setattr(
        "tools.macos.whatsapp.send_whatsapp_file",
        lambda phone, path, caption="": f"File '{os.path.basename(path)}' sent to {phone}.",
    )

    out = find_and_send_image("golden retriever", caption="hi")
    assert "sent" in out
    assert GROUP_JID in out


def test_missing_query(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel", lambda: GROUP_JID
    )
    out = find_and_send_image("   ")
    assert "query" in out


def test_no_current_channel(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel", lambda: None
    )
    out = find_and_send_image("dog")
    assert "current WhatsApp chat" in out


def test_no_results(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel", lambda: GROUP_JID
    )
    monkeypatch.setattr(
        "tools.macos.wikimedia_image_search.search_wikimedia_images",
        lambda q, limit=5: "Nenhuma imagem encontrada para a busca: 'x'",
    )
    out = find_and_send_image("dog")
    assert "No image found" in out


def test_download_error_propagates(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel", lambda: GROUP_JID
    )
    monkeypatch.setattr(
        "tools.macos.wikimedia_image_search.search_wikimedia_images",
        lambda q, limit=5: _results(),
    )
    monkeypatch.setattr(
        "tools.macos.download_file_from_url.download_file_from_url",
        lambda url, filename, category: "Error: File is too large (exceeds 100MB limit).",
    )
    out = find_and_send_image("dog")
    assert "too large" in out


def test_not_a_direct_image_url(monkeypatch):
    monkeypatch.setattr(
        "tools.macos.find_and_send_image._resolve_current_channel", lambda: GROUP_JID
    )
    monkeypatch.setattr(
        "tools.macos.wikimedia_image_search.search_wikimedia_images",
        lambda q, limit=5: _results("https://example.com/page?id=1"),
    )
    out = find_and_send_image("dog")
    assert "not a direct image URL" in out


def test_sanitize_filename_from_thumb_url():
    name = _sanitize_filename_from_wikimedia_url(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/X_Dog.jpg/640px-X_Dog.jpg",
        title="X Dog",
    )
    assert name == "X_Dog.jpg"


def test_sanitize_filename_without_extension():
    name = _sanitize_filename_from_wikimedia_url(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/1/2/foo/bar", title="My Pic"
    )
    assert name.endswith(".jpg")