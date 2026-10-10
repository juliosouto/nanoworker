import base64
from unittest.mock import MagicMock, patch

import pytest

from agent.image_generation import (
    _content_to_prompt,
    _ext_for_media_type,
    generate_image_llm,
)


@pytest.fixture
def mock_cursor():
    return MagicMock()


def _b64_response(b64, media_type="image/png", usage=None):
    return {
        "data": [{"b64_json": b64, "media_type": media_type}],
        "usage": usage or {"prompt_tokens": 5, "completion_tokens": 100},
    }


# --------------------------------------------------------------------------
# _content_to_prompt
# --------------------------------------------------------------------------

def test_content_to_prompt_plain_string():
    assert _content_to_prompt("  a red panda  ") == "a red panda"


def test_content_to_prompt_parts_list():
    parts = ["a ", MagicMock(text="red "), MagicMock(text=None), MagicMock(text="panda")]
    assert _content_to_prompt(parts) == "a \nred \npanda"


def test_content_to_prompt_truncates_long():
    assert len(_content_to_prompt("x" * 5000)) == 4000


def test_content_to_prompt_empty():
    assert _content_to_prompt("") == ""
    assert _content_to_prompt([]) == ""


# --------------------------------------------------------------------------
# _ext_for_media_type
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "media_type,expected",
    [
        ("image/png", "png"),
        ("image/jpeg", "jpg"),
        ("IMAGE/PNG", "png"),
        ("image/webp", "webp"),
        ("image/svg+xml", "svg"),
        ("application/octet-stream", "png"),  # fallback
        ("", "png"),
        (None, "png"),
    ],
)
def test_ext_for_media_type(media_type, expected):
    assert _ext_for_media_type(media_type) == expected


# --------------------------------------------------------------------------
# generate_image_llm
# --------------------------------------------------------------------------

def test_generate_image_llm_requires_api_key(mock_cursor):
    with pytest.raises(ValueError, match="API Key"):
        generate_image_llm(
            "openrouter/ming-image-0.1-design",
            [], {}, "a cat", mock_cursor, "sess", "msg", "messages_out",
            api_key=None,
        )


def test_generate_image_llm_no_prompt(mock_cursor):
    with pytest.raises(ValueError, match="text prompt"):
        generate_image_llm(
            "openrouter/ming-image-0.1-design",
            [], {}, "   ", mock_cursor, "sess", "msg", "messages_out",
            api_key="key",
        )


@patch("agent.image_generation._log_usage")
@patch("agent.image_generation.get_temp_file_path", return_value="/t/gen_abcd1234.png")
@patch("agent.image_generation.requests.post")
@patch("builtins.open", new_callable=MagicMock)
def test_generate_image_llm_b64_success(mock_open, mock_post, mock_temp, mock_log, mock_cursor):
    resp = MagicMock()
    resp.json.return_value = _b64_response(base64.b64encode(b"fakepng").decode())
    resp.raise_for_status.return_value = None
    mock_post.return_value = resp

    result = generate_image_llm(
        "openrouter/ming-image-0.1-design", [], {},
        "a red panda astronaut", mock_cursor, "sess", "msg", "messages_out",
        api_key="key",
    )

    # The model slug is sent without the openrouter/ prefix.
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["model"] == "ming-image-0.1-design"
    assert kwargs["json"]["prompt"] == "a red panda astronaut"
    assert kwargs["headers"]["Authorization"] == "Bearer key"
    # Result is a Markdown image tag served from /api/temp.
    assert "![imagem gerada](/api/temp/gen_abcd1234.png)" in result
    assert "🎨" in result
    mock_log.assert_called_once()


@patch("agent.image_generation._log_usage")
@patch("agent.image_generation.get_temp_file_path", return_value="/t/gen_cafe1234.webp")
@patch("agent.image_generation.download_file")
@patch("agent.image_generation.requests.post")
def test_generate_image_llm_url_variant(mock_post, mock_download, mock_temp, mock_log, mock_cursor):
    resp = MagicMock()
    resp.json.return_value = {
        "data": [{"url": "https://example.com/img.webp", "media_type": "image/webp"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 50},
    }
    resp.raise_for_status.return_value = None
    mock_post.return_value = resp

    result = generate_image_llm(
        "ming-image-0.1-design", [], {}, "a dog",
        mock_cursor, "sess", "msg", "messages_out", api_key="key",
    )

    mock_download.assert_called_once_with(
        "https://example.com/img.webp", "/t/gen_cafe1234.webp"
    )
    assert "/api/temp/gen_cafe1234.webp" in result


@patch("agent.image_generation.requests.post")
def test_generate_image_llm_empty_data(mock_post, mock_cursor):
    resp = MagicMock()
    resp.json.return_value = {"data": []}
    resp.raise_for_status.return_value = None
    mock_post.return_value = resp

    with pytest.raises(ValueError, match="no data"):
        generate_image_llm(
            "ming-image-0.1-design", [], {}, "a dog",
            mock_cursor, "sess", "msg", "messages_out", api_key="key",
        )


@patch("agent.image_generation._log_usage")
@patch("agent.image_generation.get_temp_file_path", return_value="/t/gen_retry999.png")
@patch("agent.image_generation.requests.post")
@patch("agent.image_generation.sleep_interruptible", return_value=False)
@patch("builtins.open", new_callable=MagicMock)
def test_generate_image_llm_retries_then_succeeds(
    mock_open, mock_sleep, mock_post, mock_temp, mock_log, mock_cursor
):
    import requests

    good = MagicMock()
    good.json.return_value = _b64_response(base64.b64encode(b"png").decode())
    good.raise_for_status.return_value = None

    rate_limited = requests.exceptions.HTTPError("429 rate limit exceeded")
    mock_post.side_effect = [rate_limited, good]

    result = generate_image_llm(
        "ming-image-0.1-design", [], {}, "a dog",
        mock_cursor, "sess", "msg", "messages_out", api_key="key",
    )

    assert mock_post.call_count == 2
    assert "/api/temp/gen_retry999.png" in result


@patch("agent.image_generation.requests.post")
def test_generate_image_llm_non_retryable_raises(mock_post, mock_cursor):
    import requests

    err = requests.exceptions.HTTPError("400 Bad Request")
    err.response = MagicMock(status_code=400, text="bad prompt")
    resp = MagicMock()
    resp.raise_for_status.side_effect = err
    mock_post.return_value = resp

    with pytest.raises(Exception):
        generate_image_llm(
            "ming-image-0.1-design", [], {}, "a dog",
            mock_cursor, "sess", "msg", "messages_out", api_key="key",
        )
    assert mock_post.call_count == 1

