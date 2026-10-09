"""Tests for modular prompt construction (Fase 1) — agent.lc.prompts."""
import pytest

from agent.lc.prompts import (
    COMPACT_RULES_TEMPLATE,
    build_system_prompt,
    compact_standard_rules,
)
from agent.lc.tokens import count_tokens


@pytest.fixture(autouse=True)
def _langchain_stack(monkeypatch):
    """Enable the LangChain stack and default structured mode for these tests."""
    monkeypatch.setenv("LLM_STACK", "langchain")
    monkeypatch.delenv("LC_STRUCTURED_OUTPUT", raising=False)


class TestCompactRules:
    def test_contains_worker_name_and_essentials(self):
        rules = compact_standard_rules("Nano")
        assert "Nano" in rules
        assert "search_web" in rules
        assert "<audio>" in rules
        assert "/app/files/" in rules

    def test_tools_rules_conditional(self):
        with_tools = compact_standard_rules("Nano", include_tool_rules=True)
        without_tools = compact_standard_rules("Nano", include_tool_rules=False)
        assert "use a tool" in with_tools
        assert "use a tool" not in without_tools

    def test_is_smaller_than_legacy_rules(self):
        """Compact rules must use materially fewer tokens than the legacy block."""
        import standard_prompts
        legacy = standard_prompts.apply_standard_rules("", worker_name="Nano")
        compact = compact_standard_rules("Nano")
        assert count_tokens(compact, mode="tiktoken") < count_tokens(legacy, mode="tiktoken")

    def test_template_has_no_unrendered_placeholders(self):
        rules = compact_standard_rules("Nano")
        for placeholder in ("{worker_name}", "{datetime}", "{location}"):
            assert placeholder not in rules

    def test_compact_template_is_langchain_prompt(self):
        from langchain_core.prompts import ChatPromptTemplate
        import agent.lc.prompts as prompts_mod
        assert isinstance(prompts_mod._compact_rules_prompt, ChatPromptTemplate)
        assert "{worker_name}" in COMPACT_RULES_TEMPLATE


class TestBuildSystemPrompt:
    def _patch(self, mocker):
        mocker.patch("agent.prompt_builder.get_config", return_value="false")
        mocker.patch("agent.prompt_builder.get_ide_config", return_value=None)
        mocker.patch("agent.prompt_builder._fetch_user_memory", return_value="")

    def test_native_structured_omits_json_schema(self, mocker):
        self._patch(mocker)
        from agent.prompt_builder import JSON_SCHEMA_PROMPT
        out = build_system_prompt(cursor=mocker.MagicMock(), native_structured=True)
        assert JSON_SCHEMA_PROMPT not in out
        assert "You MUST output" not in out

    def test_prompt_mode_keeps_json_schema(self, mocker):
        self._patch(mocker)
        from agent.prompt_builder import JSON_SCHEMA_PROMPT
        out = build_system_prompt(cursor=mocker.MagicMock(), native_structured=False)
        assert JSON_SCHEMA_PROMPT in out

    def test_worker_instructions_kept(self, mocker):
        self._patch(mocker)
        out = build_system_prompt(
            cursor=mocker.MagicMock(),
            worker={"worker_instructions": "CUSTOM BASE PROMPT"},
            worker_name="Nano",
            native_structured=True,
        )
        assert "CUSTOM BASE PROMPT" in out
        assert "Nano" in out

    def test_memory_appended(self, mocker):
        mocker.patch("agent.prompt_builder.get_config", return_value="false")
        mocker.patch("agent.prompt_builder.get_ide_config", return_value=None)
        # Fase 2: the legacy _fetch_user_memory was replaced by the RAG
        # retriever, so patch the new entry point instead.
        mocker.patch(
            "agent.lc.memory_rag.get_memory_block",
            return_value="User Memory / Persistent Instructions:\n[ID: 1] Always reply in PT-BR.",
        )
        out = build_system_prompt(cursor=mocker.MagicMock(), native_structured=True)
        assert "Always reply in PT-BR." in out

    def test_image_rules_applied(self, mocker):
        self._patch(mocker)
        out = build_system_prompt(cursor=mocker.MagicMock(), has_image=True, native_structured=True)
        assert "extract and structure literally 100%" in out

    def test_saves_tokens_vs_legacy(self, mocker):
        """End-to-end: compact rules + native structured output must use
        materially fewer tokens than the legacy builder output."""
        self._patch(mocker)
        cursor = mocker.MagicMock()
        worker = {"worker_instructions": "You are a helpful worker."}

        new = build_system_prompt(cursor=cursor, worker=worker, worker_name="Nano",
                                  native_structured=True)
        from agent.prompt_builder import build_system_prompt as legacy_build
        import agent.lc.settings as lc_settings
        mocker.patch.object(lc_settings, "stack_enabled", return_value=False)
        old = legacy_build(cursor=cursor, worker=worker, worker_name="Nano")

        assert count_tokens(new, mode="tiktoken") < count_tokens(old, mode="tiktoken")
