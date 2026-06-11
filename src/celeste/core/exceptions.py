"""Exception classes for Celeste-DAG Environment Agent Protocol."""


class PlannerTimeoutError(Exception):
    """Raised when the planner LLM call exceeds its timeout."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class SnapshotTimeoutError(Exception):
    """Raised when the snapshot tool exceeds its timeout."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class ToolTimeoutError(Exception):
    """Raised when a tool call exceeds its timeout."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class PathTraversalError(Exception):
    """Raised when the filesystem driver detects path traversal outside base_path."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class AuthenticationError(Exception):
    """Raised on WebSocket or authentication failures.

    Attributes:
        status_code: Optional HTTP status code associated with the failure.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def __str__(self) -> str:
        return self.message
