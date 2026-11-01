"""history_transcript / context_for_system_prompt (HISTORY_IN_SYSTEM_PROMPT)."""

from google.genai import types

from agent.message_processor import context_for_system_prompt, history_transcript


def _turn(role, *parts):
    return types.Content(role=role, parts=list(parts))


def test_transcript_labels_each_turn():
    history = [
        _turn("user", types.Part.from_bytes(data=b"x", mime_type="image/png"),
              types.Part.from_text(text="o que é isso?")),
        _turn("model", types.Part.from_text(text="Um gato.")),
        _turn("user", types.Part.from_text(text="[Message from: Vitor (1)]\noi")),
    ]
    assert history_transcript(history) == (
        "[User]\no que é isso?\n[1 attachment(s) not shown]\n\n"
        "[You]\nUm gato.\n\n"
        "[Message from: Vitor (1)]\noi"
    )


def test_context_sections():
    assert context_for_system_prompt([]) == ""
    out = context_for_system_prompt([_turn("model", types.Part.from_text(text="oi"))], "RAG")
    assert out.startswith("# Conversation so far\n")
    assert out.endswith("# Older messages related to the request\nRAG")
