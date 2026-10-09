"""Tests for the LangChain integration layer (agent.lc) — Fase 0.

Covers:
- agent.lc.tokens: real tiktoken counting, heuristic fallback, truncate_tail.
- agent.lc.settings: flag resolution and defaults.
"""
from agent.lc import settings as lc_settings
from agent.lc.tokens import (
    CHARS_PER_TOKEN,
    count_tokens,
    heuristic_count,
    truncate_tail,
)


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------

class TestCountTokens:
    def test_empty_values(self):
        assert count_tokens(None) == 0
        assert count_tokens("") == 0

    def test_heuristic_mode_matches_legacy_math(self):
        assert count_tokens("abcd", mode="heuristic") == 1
        assert count_tokens("a" * 4000, mode="heuristic") == 1000
        assert count_tokens("x", mode="heuristic") == 1  # never below 1

    def test_tiktoken_mode_real_count(self):
        text = "The quick brown fox jumps over the lazy dog"
        real = count_tokens(text, mode="tiktoken")
        # Real tokenizer must return a plausible, strictly-bounded count.
        assert 0 < real < len(text) // 2

    def test_tiktoken_beats_heuristic_on_word_text(self):
        text = "Hello, how are you today? I would like to know the weather in Lisbon."
        real = count_tokens(text, mode="tiktoken")
        heuristic = count_tokens(text, mode="heuristic")
        # For natural language the heuristic overestimates; tiktoken must be
        # at least as good (never wildly larger).
        assert real <= heuristic

    def test_non_string_input_is_stringified(self):
        assert count_tokens(12345, mode="heuristic") == 1

    def test_default_mode_is_tiktoken(self, monkeypatch):
        monkeypatch.delenv("LC_TOKEN_COUNTER", raising=False)
        text = "hello world, this is a token counting sanity check"
        assert count_tokens(text) == count_tokens(text, mode="tiktoken")


# ---------------------------------------------------------------------------
# heuristic_count / truncate_tail
# ---------------------------------------------------------------------------

class TestHeuristicCount:
    def test_basic(self):
        assert heuristic_count(None) == 0
        assert heuristic_count("") == 0
        assert heuristic_count("abcd") == 1
        assert heuristic_count("abcde") == 1
        assert heuristic_count("a" * 9) == 2

    def test_constant_is_four(self):
        assert CHARS_PER_TOKEN == 4


class TestTruncateTail:
    def test_noop_when_under_budget(self):
        assert truncate_tail("short text", 100, mode="heuristic") == "short text"
        assert truncate_tail("", 100, mode="heuristic") == ""

    def test_heuristic_keeps_last_chars(self):
        text = "HEAD" + "x" * 30 + "TAIL"
        out = truncate_tail(text, 5, mode="heuristic")
        assert len(out) == 20  # 5 tokens * 4 chars
        assert out.endswith("TAIL")

    def test_tiktoken_keeps_tail_within_budget(self):
        text = "word " * 200  # ~1000 chars, hundreds of tokens
        budget = 20
        out = truncate_tail(text, budget, mode="tiktoken")
        assert count_tokens(out, mode="tiktoken") <= budget
        # Tail semantics: output must be a suffix of the input.
        assert text.endswith(out)
        assert len(out) < len(text)

    def test_zero_budget_returns_original(self):
        assert truncate_tail("abc", 0, mode="tiktoken") == "abc"


# ---------------------------------------------------------------------------
# tiktoken fallback paths (offline / broken encoding)
# ---------------------------------------------------------------------------

def _simulate_missing_tiktoken(monkeypatch):
    """Makes `import tiktoken` raise and resets the module-level cache."""
    import sys
    import agent.lc.tokens as tokens_mod
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # import raises ImportError
    monkeypatch.setattr(tokens_mod, "_ENCODINGS", {})
    monkeypatch.setattr(tokens_mod, "_ENCODING_FAILED", False)
    return tokens_mod


def test_count_tokens_falls_back_when_tiktoken_missing(monkeypatch):
    tokens_mod = _simulate_missing_tiktoken(monkeypatch)
    # The tiktoken mode degrades to the legacy heuristic math.
    assert count_tokens("abcd", mode="tiktoken") == 1
    assert count_tokens("a" * 4000, mode="tiktoken") == 1000
    assert tokens_mod._ENCODING_FAILED is True  # failure is cached


def test_truncate_tail_falls_back_when_tiktoken_missing(monkeypatch):
    _simulate_missing_tiktoken(monkeypatch)
    text = "HEAD" + "x" * 30 + "TAIL"
    out = truncate_tail(text, 5, mode="tiktoken")
    assert out == text[-20:]  # heuristic tail slice


def test_count_tokens_encode_failure_uses_heuristic(monkeypatch):
    """A present-but-broken encoding (encode raising) must not crash."""
    import agent.lc.tokens as tokens_mod

    class BadEnc:
        def encode(self, *args, **kwargs):
            raise RuntimeError("boom")

        def decode(self, tokens):
            raise RuntimeError("boom")

    monkeypatch.setitem(tokens_mod._ENCODINGS, tokens_mod._ENCODING_NAME, BadEnc())
    assert count_tokens("abcd", mode="tiktoken") == 1
    text = "HEAD" + "x" * 30 + "TAIL"
    assert truncate_tail(text, 5, mode="tiktoken") == text[-20:]


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_stack_default_is_langchain(self, monkeypatch):
        # Fase 6: LLM_STACK defaults to the LangChain stack.
        monkeypatch.delenv("LLM_STACK", raising=False)
        assert lc_settings.stack_enabled() is True

    def test_stack_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("LLM_STACK", "langchain")
        assert lc_settings.stack_enabled() is True

    def test_stack_legacy_via_env(self, monkeypatch):
        # Rollback hatch kept for one release.
        monkeypatch.setenv("LLM_STACK", "legacy")
        assert lc_settings.stack_enabled() is False

    def test_stack_unknown_value_warns_once_and_is_legacy(self, monkeypatch, mocker):
        monkeypatch.setenv("LLM_STACK", "banana")
        lc_settings._warned_stack_values.clear()
        mock_warn = mocker.patch.object(lc_settings.logger, "warning")
        assert lc_settings.stack_enabled() is False
        assert lc_settings.stack_enabled() is False
        assert mock_warn.call_count == 1

    def test_cfg_returns_default_when_db_unavailable(self, mocker):
        mocker.patch("database.get_config", side_effect=RuntimeError("no db"))
        assert lc_settings._cfg("ANY_KEY", "fallback") == "fallback"
        assert lc_settings.memory_top_k() == 5  # still degrades safely

    def test_token_counter_mode_env_override(self, monkeypatch):
        monkeypatch.setenv("LC_TOKEN_COUNTER", "heuristic")
        assert lc_settings.token_counter_mode() == "heuristic"

    def test_token_counter_mode_unknown_falls_back_to_tiktoken(self, monkeypatch):
        monkeypatch.setenv("LC_TOKEN_COUNTER", "banana")
        assert lc_settings.token_counter_mode() == "tiktoken"

    def test_token_counter_default(self, monkeypatch):
        monkeypatch.delenv("LC_TOKEN_COUNTER", raising=False)
        assert lc_settings.token_counter_mode() == "tiktoken"

    def test_numeric_settings_defaults(self, monkeypatch):
        monkeypatch.delenv("LC_MEMORY_TOP_K", raising=False)
        monkeypatch.delenv("LC_TOOL_RESULT_MAX_CHARS", raising=False)
        monkeypatch.delenv("LC_KEEP_RECENT_MSGS", raising=False)
        assert lc_settings.memory_top_k() == 5
        assert lc_settings.tool_result_max_chars() == 6000
        assert lc_settings.keep_recent_messages() == 8

    def test_numeric_settings_from_db(self, mocker):
        values = {
            "LC_MEMORY_TOP_K": "3",
            "LC_TOOL_RESULT_MAX_CHARS": "1000",
            "LC_KEEP_RECENT_MSGS": "12",
        }
        mocker.patch("database.get_config", side_effect=lambda k, d=None: values.get(k, d))
        assert lc_settings.memory_top_k() == 3
        assert lc_settings.tool_result_max_chars() == 1000
        assert lc_settings.keep_recent_messages() == 12

    def test_numeric_settings_invalid_fall_back_to_default(self, mocker):
        mocker.patch("database.get_config", return_value="not-a-number")
        assert lc_settings.memory_top_k() == 5
        assert lc_settings.tool_result_max_chars() == 6000
        assert lc_settings.keep_recent_messages() == 8

    def test_numeric_settings_env_override_wins(self, monkeypatch, mocker):
        monkeypatch.setenv("LC_MEMORY_TOP_K", "9")
        mocker.patch("database.get_config", return_value="2")
        assert lc_settings.memory_top_k() == 9

    def test_numeric_settings_below_minimum_clamped(self, monkeypatch):
        monkeypatch.setenv("LC_MEMORY_TOP_K", "0")
        monkeypatch.setenv("LC_TOOL_RESULT_MAX_CHARS", "-5")
        assert lc_settings.memory_top_k() == 1
        assert lc_settings.tool_result_max_chars() == 0


# ---------------------------------------------------------------------------
# slice_conversation_to_budget (tiktoken mode, O(n) drop-oldest)
# ---------------------------------------------------------------------------

def _msg(text, role="user"):
    from google.genai import types
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


def test_slice_tiktoken_drops_oldest_and_keeps_newest(mocker, monkeypatch):
    monkeypatch.setenv("LC_TOKEN_COUNTER", "tiktoken")
    mocker.patch("database.get_config", return_value="30")  # 30-token budget
    from utils.message_utils import slice_conversation_to_budget
    from agent.lc.tokens import count_tokens

    history = [_msg("hello there old message " * 10),   # large old msg
               _msg("middle reply " * 10, "model"),     # large middle msg
               _msg("newest")]                          # 1-token newest
    current = "current question"
    h2, cur = slice_conversation_to_budget(history, current)

    assert h2[-1] is history[-1]  # newest kept, order preserved
    assert cur == current         # short current message untouched
    assert h2, "newest message must survive the budget slice"
    # Combined budget must hold after dropping oldest (or only newest remains).
    total = sum(count_tokens(p.text, mode="tiktoken") for m in h2 for p in m.parts)
    total += count_tokens(current, mode="tiktoken")
    assert total <= 30


def test_slice_tiktoken_noop_when_under_budget(mocker, monkeypatch):
    monkeypatch.setenv("LC_TOKEN_COUNTER", "tiktoken")
    mocker.patch("database.get_config", return_value="5000")
    from utils.message_utils import slice_conversation_to_budget

    history = [_msg("short"), _msg("reply", "model")]
    h2, cur = slice_conversation_to_budget(history, "question")
    assert h2 == history
    assert cur == "question"


def test_slice_tiktoken_truncates_current_when_alone_over_budget(mocker, monkeypatch):
    monkeypatch.setenv("LC_TOKEN_COUNTER", "tiktoken")
    mocker.patch("database.get_config", return_value="10")
    from utils.message_utils import slice_conversation_to_budget
    from agent.lc.tokens import count_tokens

    current = "word " * 200  # ~200 tokens, far over the 10-token budget
    h2, cur = slice_conversation_to_budget([], current)
    assert count_tokens(cur, mode="tiktoken") <= 10
    assert current.endswith(cur)  # tail semantics


def test_slice_heuristic_branch_preserves_legacy_result(mocker, monkeypatch):
    """The O(n) refactor must produce the exact same result as the legacy
    char-based loop for the documented legacy scenarios."""
    monkeypatch.setenv("LC_TOKEN_COUNTER", "heuristic")
    mocker.patch("database.get_config", return_value="5")  # 5 tokens = 20 chars
    from utils.message_utils import slice_conversation_to_budget

    history = [_msg("A" * 15), _msg("B" * 15, "model"), _msg("C" * 15)]
    h2, cur = slice_conversation_to_budget(history, "tail")
    assert len(h2) == 1
    assert h2[0].parts[0].text == "C" * 15
    assert cur == "tail"


def test_unknown_counter_mode_warns_once_per_value(mocker, monkeypatch):
    monkeypatch.setenv("LC_TOKEN_COUNTER", "banana")
    lc_settings._warned_counter_values.clear()
    mock_warn = mocker.patch.object(lc_settings.logger, "warning")
    assert lc_settings.token_counter_mode() == "tiktoken"
    assert lc_settings.token_counter_mode() == "tiktoken"
    assert mock_warn.call_count == 1
