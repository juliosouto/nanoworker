"""Scheduled runs can stay silent with NO_REPLY."""

from unittest.mock import MagicMock, patch

import sweeper


def test_strip_silent_token():
    assert sweeper.strip_silent_token("NO_REPLY") == ""
    assert sweeper.strip_silent_token("  `NO_REPLY`. ") == ""
    assert sweeper.strip_silent_token("Apaguei a mensagem do João.") == "Apaguei a mensagem do João."


def test_prompt_mentions_token_and_job_id():
    prompt = sweeper.scheduled_task_prompt("job-1", "check X")
    assert "NO_REPLY" in prompt and "job-1" in prompt and prompt.endswith("check X")


def _post_calls(text):
    post = MagicMock()
    with patch("requests.post", post), \
         patch("utils.audio_utils.extract_and_generate_audio", side_effect=lambda t: (t, None)):
        sweeper.make_baileys_callback("1@g.us")(text)
    return post.call_args_list


def test_baileys_callback_silent_and_progress_send_nothing():
    assert _post_calls("NO_REPLY") == []
    assert _post_calls("Agent reflecting...") == []


def test_baileys_callback_sends_real_answer():
    calls = _post_calls("Apaguei a mensagem.")
    assert calls[0].kwargs["json"] == {"text": "Apaguei a mensagem.", "jid": "1@g.us"}


def test_scheduling_and_whatsapp_tools_survive_the_relevance_filter():
    from agent.message_processor import _is_always_kept_tool
    from tools.linux import scheduling, whatsapp
    from tools import weather

    assert _is_always_kept_tool(scheduling.schedule_task)
    assert _is_always_kept_tool(scheduling.delete_scheduled_task)
    assert _is_always_kept_tool(whatsapp.send_whatsapp_file)
    assert not _is_always_kept_tool(weather.get_weather)
