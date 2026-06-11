"""Tests for ContextWindowManager."""

import pytest

from celeste_dag.core.context_window import ContextWindowManager


class TestContextWindowManager:
    def test_context_window_adds_messages(self):
        mgr = ContextWindowManager(max_tokens=8000)
        mgr.add_message("system", "You are a helpful assistant.")
        mgr.add_message("user", "Hello!")
        msgs = mgr.get_messages()
        assert len(msgs) == 2
        assert msgs[0] == {"role": "system", "content": "You are a helpful assistant."}
        assert msgs[1] == {"role": "user", "content": "Hello!"}

    def test_context_window_truncates_oldest_first(self):
        mgr = ContextWindowManager(max_tokens=100)
        # Use long content so total tokens exceed the target
        mgr.add_message("system", "x" * 40)   # 10 tokens
        mgr.add_message("user", "x" * 40)     # 10 tokens
        mgr.add_message("assistant", "x" * 40)  # 10 tokens
        mgr.add_message("user", "x" * 40)     # 10 tokens
        # Truncate to a small target so oldest messages are removed
        mgr.truncate_to_fit(target_tokens=20)
        msgs = mgr.get_messages()
        # Oldest messages removed; newest message(s) remain
        assert len(msgs) <= 2
        assert msgs[-1] == {"role": "user", "content": "x" * 40}

    def test_context_window_estimates_tokens(self):
        mgr = ContextWindowManager(max_tokens=8000)
        # 40 chars should estimate to ~10 tokens (4 chars per token)
        content = "a" * 40
        mgr.add_message("user", content)
        estimated = mgr.estimate_tokens(mgr.get_messages())
        assert estimated == 10

    def test_context_window_empty_after_clear(self):
        mgr = ContextWindowManager(max_tokens=8000)
        mgr.add_message("user", "Hello")
        mgr.add_message("assistant", "Hi there")
        mgr.clear()
        assert mgr.get_messages() == []
