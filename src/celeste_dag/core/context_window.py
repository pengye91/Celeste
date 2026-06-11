"""ContextWindowManager for managing LLM prompt context windows."""


class ContextWindowManager:
    """Manages a sliding window of messages for LLM prompts with token estimation."""

    def __init__(self, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens
        self._messages: list[dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the context window."""
        self._messages.append({"role": role, "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        """Return the current list of messages."""
        return list(self._messages)

    def estimate_tokens(self, messages: list[dict[str, str]] | None = None) -> int:
        """Estimate token count using a simple heuristic (4 chars ~ 1 token)."""
        msgs = messages if messages is not None else self._messages
        total_chars = sum(len(m["content"]) for m in msgs)
        return total_chars // 4

    def truncate_to_fit(self, target_tokens: int) -> None:
        """Remove oldest messages until estimated tokens <= target_tokens."""
        while self._messages and self.estimate_tokens() > target_tokens:
            self._messages.pop(0)

    def summarize(self, messages: list[dict[str, str]]) -> str:
        """Placeholder summarization returning a summary string."""
        return f"Summary of {len(messages)} message(s)"

    def clear(self) -> None:
        """Clear all messages from the context window."""
        self._messages.clear()
