from __future__ import annotations

import json

from app.ai.chat.models import ChatContext, ChatRequest, ReadingContext
from app.ai.chat.service import CHAT_SYSTEM_PROMPT, build_chat_prompt
from app.models.reading_actions import (
    READING_ACTION_KEYS,
    READING_ACTION_SPECS,
    READING_CONTEXT_TRANSLATE,
    READING_EXPLAIN,
    READING_SECTION_ROLE,
    READING_SUMMARIZE,
    reading_action_prompt,
)


def test_stage5_reading_actions_are_unique_and_stable() -> None:
    stage5_keys = {
        READING_EXPLAIN,
        READING_CONTEXT_TRANSLATE,
        READING_SUMMARIZE,
        READING_SECTION_ROLE,
    }
    assert stage5_keys <= READING_ACTION_KEYS
    assert len({spec.key for spec in READING_ACTION_SPECS}) == len(READING_ACTION_SPECS)
    assert [spec.label for spec in READING_ACTION_SPECS[:4]] == [
        "解释这段",
        "结合上下文翻译",
        "总结这段",
        "分析段落作用",
    ]


def test_context_translate_action_carries_the_configured_target_language() -> None:
    prompt = reading_action_prompt(
        READING_CONTEXT_TRANSLATE,
        target_language="ja",
    )

    assert "ja" in prompt
    assert "术语" in prompt
    assert "公式" in prompt


def test_non_translation_reading_actions_remain_concise_user_prompts() -> None:
    for key in (READING_EXPLAIN, READING_SUMMARIZE, READING_SECTION_ROLE):
        prompt = reading_action_prompt(key, target_language="de")
        assert prompt
        assert "{target_language}" not in prompt
        assert len(prompt) < 120


def test_reading_action_prompt_is_grounded_by_selected_and_nearby_context() -> None:
    request = ChatRequest(
        session_id="stage5",
        user_message=reading_action_prompt(READING_EXPLAIN),
        context=ChatContext(
            source_text="The LLM performs local refinement.",
            translated_text="LLM 执行局部细化。",
            reading=ReadingContext(
                resource_url="https://example.org/paper",
                resource_title="A Research Paper",
                section_heading="3. Methodology",
                context_before="The GP first identifies a promising region.",
                context_after="Candidates are then validated deterministically.",
                source_kind="browser_selection",
            ),
        ),
    )

    prompt = build_chat_prompt(request)
    payload = json.loads(prompt.split("\n\n", 1)[1])

    assert payload["selected_context"]["source_text"] == (
        "The LLM performs local refinement."
    )
    assert payload["reading_context"]["section_heading"] == "3. Methodology"
    assert "selected_context.source_text" in CHAT_SYSTEM_PROMPT
    assert "bounded before/after context" in CHAT_SYSTEM_PROMPT
