"""
Routing tests for image-only models.

Models registered with image_output=1 and text_output=0 (e.g.
OpenRouter's inclusionai/ming-image-0.1-design) must be diverted to the
dedicated image-generation backend instead of the chat/completions provider
loops, and this must hold for BOTH the legacy and the LangChain stacks.
"""

from unittest.mock import MagicMock, patch


def _row(provider="openrouter", image_output=1, text_output=0):
    return {
        "provider": provider,
        "api_key": "enc",
        "thinking": 0,
        "context_window": 8000,
        "max_output_tokens": 1024,
        "image_output": image_output,
        "text_output": text_output,
    }


def _call(model_name, is_ide=False, summarize=False):
    from agent.llm_router import route_llm_call

    return route_llm_call(
        model_name,
        [],
        {},
        "draw a cat",
        MagicMock(),
        "sess",
        "msg",
        is_ide=is_ide,
        summarize=summarize,
    )


@patch("agent.llm_router.lc_settings.stack_enabled", return_value=False)
@patch("database.decrypt_value", return_value="dec-key")
@patch("agent.image_generation.generate_image_llm")
@patch("agent.llm_providers.call_openrouter_llm")
@patch("database.get_db")
def test_image_only_model_routes_to_image_backend(
    mock_get_db, mock_chat, mock_img, mock_dec, mock_stack
):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = _row()
    conn.cursor.return_value = cur
    mock_get_db.return_value = conn

    mock_img.return_value = "🎨 Imagem gerada:\n![imagem gerada](/api/temp/gen_x.png)"
    result = _call("openrouter/ming-image-0.1-design")

    mock_img.assert_called_once()
    # The chat provider must NOT be hit.
    mock_chat.assert_not_called()
    assert "/api/temp/gen_x.png" in result


@patch("agent.llm_router.lc_settings.stack_enabled", return_value=True)
@patch("database.decrypt_value", return_value="dec-key")
@patch("agent.image_generation.generate_image_llm")
@patch("agent.lc.runner.run_langchain_llm")
@patch("database.get_db")
def test_image_only_model_routes_before_langchain_runner(
    mock_get_db, mock_runner, mock_img, mock_dec, mock_stack
):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = _row()
    conn.cursor.return_value = cur
    mock_get_db.return_value = conn

    mock_img.return_value = "🎨 Imagem gerada:\n![imagem gerada](/api/temp/gen_y.png)"
    result = _call("openrouter/ming-image-0.1-design")

    mock_img.assert_called_once()
    mock_runner.assert_not_called()
    assert "/api/temp/gen_y.png" in result


@patch("agent.llm_router.lc_settings.stack_enabled", return_value=False)
@patch("database.decrypt_value", return_value="dec-key")
@patch("agent.image_generation.generate_image_llm")
@patch("agent.llm_providers.call_openrouter_llm")
@patch("database.get_db")
def test_summarize_backend_does_not_divert_to_image(
    mock_get_db, mock_chat, mock_img, mock_dec, mock_stack
):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = _row()
    conn.cursor.return_value = cur
    mock_get_db.return_value = conn

    mock_chat.return_value = "summary text"
    result = _call("openrouter/ming-image-0.1-design", summarize=True)

    # As a summarizer backend it stays on the text path (chat provider).
    mock_img.assert_not_called()
    mock_chat.assert_called_once()
    assert result == "summary text"


@patch("agent.llm_router.lc_settings.stack_enabled", return_value=False)
@patch("database.decrypt_value", return_value="dec-key")
@patch("agent.image_generation.generate_image_llm")
@patch("agent.llm_providers.call_openrouter_llm")
@patch("database.get_db")
def test_text_and_image_model_not_diverted(
    mock_get_db, mock_chat, mock_img, mock_dec, mock_stack
):
    # image_output=1 AND text_output=1 -> multimodal via chat, not diverted.
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = _row(image_output=1, text_output=1)
    conn.cursor.return_value = cur
    mock_get_db.return_value = conn

    mock_chat.return_value = "text with image"
    _call("openrouter/some-multimodal-model")

    mock_img.assert_not_called()
    mock_chat.assert_called_once()


@patch("agent.llm_router.lc_settings.stack_enabled", return_value=False)
@patch("database.decrypt_value", return_value="dec-key")
@patch("agent.image_generation.generate_image_llm")
@patch("agent.llm_providers.call_openrouter_llm")
@patch("database.get_db")
def test_image_only_non_openrouter_raises(
    mock_get_db, mock_chat, mock_img, mock_dec, mock_stack
):
    import pytest

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = _row(provider="gemini")
    conn.cursor.return_value = cur
    mock_get_db.return_value = conn

    with pytest.raises(ValueError, match="only implemented for OpenRouter"):
        _call("gemini-image-model")
    mock_img.assert_not_called()
