"""One status reply per turn on WhatsApp: edited at each step, then replaced by the answer."""

from unittest.mock import MagicMock, patch

import pytest

from agent import status


class FakeBaileys:
    """Records /send and /delete calls; edits keep the original id."""

    def __init__(self, edit_ok=True):
        self.calls = []
        self.edit_ok = edit_ok
        self.next_id = 0

    def post(self, url, json=None, timeout=None):
        self.calls.append((url.rsplit("/", 1)[-1], dict(json or {})))
        resp = MagicMock(status_code=200, text="ok")
        if url.endswith("/send"):
            if json.get("edit_msg_id") and self.edit_ok:
                resp.json.return_value = {"message_id": json["edit_msg_id"], "edited": True}
            else:
                self.next_id += 1
                resp.json.return_value = {"message_id": f"m{self.next_id}", "edited": False}
        return resp

    def sends(self):
        return [body for kind, body in self.calls if kind == "send"]


@pytest.fixture
def baileys():
    fake = FakeBaileys()
    with patch("routes.webhooks.req.post", side_effect=fake.post), \
            patch("utils.audio_utils.extract_and_generate_audio", side_effect=lambda t: (t, None)), \
            patch("database.insert_message_history", return_value=None) as history:
        fake.history = history
        yield fake


def _callback():
    from routes.webhooks import _build_wa_callback

    return _build_wa_callback("5511@s.whatsapp.net", reply_to_msg_id="user-msg")


def test_statuses_edit_one_reply_and_the_answer_replaces_it(baileys):
    cb = _callback()
    cb.report_status(status.THINKING)
    cb.report_status(status.tool_status("search_web"))
    cb.report_status(status.tool_status("search_web"))  # duplicate: skipped
    cb("⚙️ Executed tools: search_web\nResults:\n- raw stuff")  # becomes a status
    cb("⏳ Model overloaded (503) on attempt 1/2. Waiting 5s to retry...")
    cb("Resposta final")

    sends = baileys.sends()
    assert sends[0] == {"text": status.THINKING, "jid": "5511@s.whatsapp.net", "quoted_msg_id": "user-msg"}
    assert [s["text"] for s in sends[1:]] == [
        "🌐 Buscando na web...", status.ANALYZING,
        "⏳ Model overloaded (503) on attempt 1/2. Waiting 5s to retry...", "Resposta final",
    ]
    assert all(s.get("edit_msg_id") == "m1" for s in sends[1:])
    assert not any(kind == "delete" for kind, _ in baileys.calls)
    assert baileys.history.call_args.kwargs["message_id"] == "m1"
    assert baileys.history.call_args.kwargs["content"] == "Resposta final"


def test_answer_without_status_is_a_plain_reply(baileys):
    _callback()("Resposta final")
    assert baileys.sends() == [{"text": "Resposta final", "jid": "5511@s.whatsapp.net",
                                "quoted_msg_id": "user-msg"}]


def test_failed_edit_falls_back_and_cleans_up(baileys):
    baileys.edit_ok = False
    cb = _callback()
    cb.report_status(status.THINKING)  # m1
    cb("Resposta final")  # edit fails -> worker sends m2; m1 is deleted
    assert ("delete", {"message_id": "m1", "jid": "5511@s.whatsapp.net"}) in baileys.calls
    assert baileys.history.call_args.kwargs["message_id"] == "m2"


def test_image_answer_drops_the_status_reply(baileys):
    cb = _callback()
    cb.report_status(status.THINKING)
    with patch("routes.webhooks.extract_and_send_images", return_value=("caption", 1)):
        cb("![img](/api/temp/x.png) caption")
    assert ("delete", {"message_id": "m1", "jid": "5511@s.whatsapp.net"}) in baileys.calls
    assert len(baileys.sends()) == 1  # only the status; the caption went with the image


def test_tool_status_names():
    assert status.tool_status("search_web") == "🌐 Buscando na web..."
    assert status.tool_status("get_weather") == "🌤️ Consultando o clima..."
    assert status.tool_status("frobnicate") == "🔧 Usando a ferramenta frobnicate..."


def test_report_status_without_reporter_is_a_no_op():
    status.report_status("nothing happens")  # no reporter installed
    calls = []
    token = status.set_status_reporter(calls.append)
    try:
        status.report_status(status.THINKING)
    finally:
        status.reset_status_reporter(token)
    assert calls == [status.THINKING]
