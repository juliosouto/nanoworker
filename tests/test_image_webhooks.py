from unittest.mock import MagicMock, patch


# --------------------------------------------------------------------------
# extract_and_send_images
# --------------------------------------------------------------------------

@patch("routes.webhooks.req.post")
def test_extract_and_send_images_sends_media(mock_post):
    from routes.webhooks import extract_and_send_images

    mock_post.return_value = MagicMock(status_code=200, text="ok")

    with patch(
        "routes.webhooks._resolve_temp_image_path",
        side_effect=lambda f: f"/tmp/files/temp/{f}",
    ):
        remaining, sent = extract_and_send_images(
            "Aqui está ![imagem](/api/temp/gen_a1.png) a imagem",
            "wa_jid",
        )

    assert sent == 1
    assert remaining == "Aqui está  a imagem"
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["file_path"] == "/tmp/files/temp/gen_a1.png"
    assert kwargs["json"]["mimetype"] == "image/png"
    assert kwargs["json"]["jid"] == "wa_jid"
    # The remaining text rides along as the first image's caption.
    assert "Aqui está" in kwargs["json"]["caption"]


@patch("routes.webhooks.req.post")
def test_extract_and_send_images_no_image(mock_post):
    from routes.webhooks import extract_and_send_images

    remaining, sent = extract_and_send_images("just text", "wa_jid")

    assert remaining == "just text"
    assert sent == 0
    mock_post.assert_not_called()


@patch("routes.webhooks.req.post")
def test_extract_and_send_images_multiple(mock_post):
    from routes.webhooks import extract_and_send_images

    mock_post.return_value = MagicMock(status_code=200, text="ok")

    with patch(
        "routes.webhooks._resolve_temp_image_path",
        side_effect=lambda f: f"/tmp/files/temp/{f}",
    ):
        remaining, sent = extract_and_send_images(
            "text ![a](/api/temp/gen_1.png) ![b](/api/temp/gen_2.webp)",
            "wa_jid",
        )

    assert sent == 2
    assert mock_post.call_count == 2
    # Only the first image carries the caption; the second has an empty one.
    captions = [c.kwargs["json"]["caption"] for c in mock_post.call_args_list]
    assert "text" in captions[0]
    assert captions[1] == ""


@patch("routes.webhooks.req.post")
def test_extract_and_send_images_image_only_no_caption(mock_post):
    # The image-generation backend now returns ONLY the Markdown tag (the short
    # "Gerando imagem..." text was already streamed as feedback). WhatsApp must
    # deliver the image with an empty caption and no leftover text.
    from routes.webhooks import extract_and_send_images

    mock_post.return_value = MagicMock(status_code=200, text="ok")

    with patch(
        "routes.webhooks._resolve_temp_image_path",
        side_effect=lambda f: f"/tmp/files/temp/{f}",
    ):
        remaining, sent = extract_and_send_images(
            "![imagem gerada](/api/temp/gen_only.png)",
            "wa_jid",
        )

    assert sent == 1
    assert remaining == ""
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["file_path"] == "/tmp/files/temp/gen_only.png"
    assert kwargs["json"]["caption"] == ""


def test_resolve_temp_image_path_rejects_traversal(tmp_path):
    from routes.webhooks import _resolve_temp_image_path

    temp_dir = tmp_path / "files" / "temp"
    temp_dir.mkdir(parents=True)
    real_file = temp_dir / "gen_real.png"
    real_file.write_bytes(b"x")

    with patch(
        "utils.file_utils.get_temp_dir", return_value=str(temp_dir)
    ):
        # A legitimate file inside the temp dir resolves to its absolute path.
        resolved = _resolve_temp_image_path("gen_real.png")
        assert resolved == str(real_file)
        # A path escaping the temp dir must resolve to None.
        assert _resolve_temp_image_path("../../etc/passwd") is None
        # A non-existent file resolves to None.
        assert _resolve_temp_image_path("nope.png") is None
