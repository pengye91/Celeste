"""Tests for Celeste-DAG Environment Agent Protocol."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.exceptions import (
    AuthenticationError,
    PathTraversalError,
    PlannerTimeoutError,
    SnapshotTimeoutError,
    ToolTimeoutError,
)
from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


# ===========================================================================
# Exception tests
# ===========================================================================


class TestPlannerTimeoutError:
    def test_planner_timeout_error_message(self):
        msg = "Planner LLM call exceeded 30s timeout"
        exc = PlannerTimeoutError(msg)
        assert str(exc) == msg
        assert exc.args[0] == msg


class TestSnapshotTimeoutError:
    def test_snapshot_timeout_error_message(self):
        msg = "Snapshot tool exceeded 10s timeout"
        exc = SnapshotTimeoutError(msg)
        assert str(exc) == msg
        assert exc.args[0] == msg


class TestToolTimeoutError:
    def test_tool_timeout_error_message(self):
        msg = "Tool call 'ls' exceeded 5s timeout"
        exc = ToolTimeoutError(msg)
        assert str(exc) == msg
        assert exc.args[0] == msg


class TestPathTraversalError:
    def test_path_traversal_error_message(self):
        msg = "Path /etc/passwd escapes base /tmp/workspace"
        exc = PathTraversalError(msg)
        assert str(exc) == msg
        assert exc.args[0] == msg


class TestAuthenticationError:
    def test_authentication_error_with_status_code(self):
        msg = "WebSocket authentication failed"
        exc = AuthenticationError(msg, status_code=401)
        assert str(exc) == msg
        assert exc.args[0] == msg
        assert exc.status_code == 401

    def test_authentication_error_default_status_code(self):
        msg = "Authentication failed"
        exc = AuthenticationError(msg)
        assert str(exc) == msg
        assert exc.args[0] == msg
        assert exc.status_code is None


# ===========================================================================
# Mock toolkit fixture
# ===========================================================================


class MockToolkit(BaseToolkit):
    """A mock toolkit for testing agent routing."""

    @property
    def name(self):
        return "mock"

    @property
    def description(self):
        return "Mock toolkit for testing"

    def get_tools(self):
        return [
            ToolDefinition(
                name="mock_tool",
                description="A mock tool",
                parameters=[
                    ToolParameter(
                        name="arg",
                        type="integer",
                        description="An argument",
                        required=True,
                    ),
                ],
                returns="A mock result",
            ),
        ]

    def get_tool(self, name):
        for tool in self.get_tools():
            if tool.name == name:
                return tool
        return None

    async def execute(self, name, arguments, driver):
        if name == "mock_tool":
            return {"result": "mock", "arg": arguments.get("arg")}
        return {"error": "tool_not_found", "tool_name": name}


# ===========================================================================
# EnvironmentAgent tests
# ===========================================================================


class TestEnvironmentAgentLifecycle:
    @pytest.mark.asyncio
    async def test_agent_in_process_start_stop_is_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(workdir=tmpdir, toolkits=[])
            assert agent.is_running is False
            await agent.start()
            assert agent.is_running is True
            await agent.stop()
            assert agent.is_running is False


class TestEnvironmentAgentBuiltinTools:
    @pytest.fixture
    def agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(workdir=tmpdir, toolkits=[])
            yield agent

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_snapshot(self, agent):
        # Create a test file in the workdir
        Path(agent._workdir) / "test.txt"
        Path(agent._workdir, "test.txt").write_text("hello")

        result = await agent.call_tool("snapshot", {"paths": [agent._workdir]})
        assert "files" in result
        # TODO-8: the recursive snapshot now reports per-file metadata keyed
        # by the file path (not a one-level {dir: [names]} listing). The
        # legacy shallow shape is still available via recursive=False.
        test_file = str(Path(agent._workdir, "test.txt"))
        assert test_file in result["files"]
        assert "modified_time" in result["files"][test_file]
        assert "platform" in result
        assert result["platform"] != ""

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_read_file(self, agent):
        readme = Path(agent._workdir) / "readme.md"
        readme.write_text("# Hello")

        result = await agent.call_tool("read_file", {"path": str(readme)})
        assert result["content"] == "# Hello"
        assert result["size"] == 7

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_run_command(self, agent):
        result = await agent.call_tool(
            "run_command", {"command": "echo", "args": ["hello"]}
        )
        assert result["exit_code"] == 0
        assert result["stdout"].strip() == "hello"

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_write_file(self, agent):
        test_path = Path(agent._workdir) / "new.py"
        result = await agent.call_tool(
            "write_file",
            {"path": str(test_path), "content": "print('hi')"},
        )
        assert result["success"] is True
        assert result["size"] == 11
        assert test_path.read_text() == "print('hi')"

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_list_directory(self, agent):
        (Path(agent._workdir) / "a.txt").write_text("a")
        (Path(agent._workdir) / "b.txt").write_text("b")

        result = await agent.call_tool(
            "list_directory", {"path": agent._workdir}
        )
        assert "files" in result
        assert "a.txt" in result["files"]
        assert "b.txt" in result["files"]

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_stat(self, agent):
        test_file = Path(agent._workdir) / "stat_test.txt"
        test_file.write_text("content")

        result = await agent.call_tool("stat", {"path": str(test_file)})
        assert "size" in result
        assert result["size"] == 7
        assert "modified_time" in result
        assert "permissions" in result

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_check_command(self, agent):
        result = await agent.call_tool("check_command", {"command": "echo"})
        assert "available" in result
        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_agent_call_tool_builtin_discover_tools(self, agent):
        result = await agent.call_tool("discover_tools", {})
        assert isinstance(result, list)
        assert len(result) > 0
        names = [t["name"] for t in result]
        assert "read_file" in names
        assert "run_command" in names


class TestEnvironmentAgentToolkitRouting:
    @pytest.fixture
    def agent_with_toolkit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(
                workdir=tmpdir, toolkits=[MockToolkit()]
            )
            yield agent

    @pytest.mark.asyncio
    async def test_agent_call_tool_routes_to_toolkit(self, agent_with_toolkit):
        result = await agent_with_toolkit.call_tool(
            "mock_tool", {"arg": 1}
        )
        assert result["result"] == "mock"
        assert result["arg"] == 1

    @pytest.mark.asyncio
    async def test_agent_call_tool_not_found_returns_error(self, agent_with_toolkit):
        result = await agent_with_toolkit.call_tool("nonexistent", {})
        assert result["error"] == "tool_not_found"
        assert result["tool_name"] == "nonexistent"


class TestEnvironmentAgentSecurity:
    @pytest.fixture
    def agent_with_mock_security(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_auditor = MagicMock()
            mock_auditor.audit_command = AsyncMock(
                return_value=MagicMock(is_safe=False)
            )
            agent = EnvironmentAgent.in_process(
                workdir=tmpdir,
                toolkits=[],
                security_auditor=mock_auditor,
            )
            yield agent

    @pytest.mark.asyncio
    async def test_agent_call_tool_security_audit_blocks(self, agent_with_mock_security):
        result = await agent_with_mock_security.call_tool(
            "run_command", {"command": "rm", "args": ["-rf", "/"]}
        )
        assert result["error"] == "security_audit_failed"


class TestEnvironmentAgentRegistry:
    @pytest.fixture
    def agent_with_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from celeste.tools.tool_registry import ToolRegistry

            registry = ToolRegistry()
            agent = EnvironmentAgent.in_process(
                workdir=tmpdir, toolkits=[], tool_registry=registry
            )
            yield agent

    @pytest.mark.asyncio
    async def test_agent_call_tool_tool_registry_blocks(self, agent_with_empty_registry):
        result = await agent_with_empty_registry.call_tool(
            "run_command", {"command": "echo", "args": ["hi"]}
        )
        assert result["error"] == "tool_not_allowed"
        assert result["tool_name"] == "run_command"


class TestEnvironmentAgentTimeout:
    @pytest.fixture
    def agent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(workdir=tmpdir, toolkits=[])
            yield agent

    @pytest.mark.asyncio
    async def test_agent_call_tool_timeout_raises(self, agent):
        # Use a very short timeout on a slow command
        result = await agent.call_tool(
            "run_command",
            {"command": "sleep", "args": ["10"]},
            timeout_ms=100,
        )
        assert result["error"] == "tool_timeout"
        assert result["timeout_ms"] == 100


class TestEnvironmentAgentListTools:
    @pytest.fixture
    def agent_with_toolkit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(
                workdir=tmpdir, toolkits=[MockToolkit()]
            )
            yield agent

    @pytest.mark.asyncio
    async def test_agent_list_tools_returns_union(self, agent_with_toolkit):
        tools = await agent_with_toolkit.list_tools()
        # Built-in tools + 1 from mock toolkit
        names = [t["name"] for t in tools]
        assert "read_file" in names
        assert "run_command" in names
        assert "mock_tool" in names
        # Each tool should have MCP schema fields
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


class TestEnvironmentAgentRegisterToolkit:
    @pytest.mark.asyncio
    async def test_agent_register_toolkit_duplicate_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = EnvironmentAgent.in_process(workdir=tmpdir, toolkits=[])

            class ToolkitA(MockToolkit):
                async def execute(self, name, arguments, driver):
                    return {"from": "A"}

            class ToolkitB(MockToolkit):
                async def execute(self, name, arguments, driver):
                    return {"from": "B"}

            agent.register_toolkit(ToolkitA())
            agent.register_toolkit(ToolkitB())

            result = await agent.call_tool("mock_tool", {"arg": 1})
            assert result["from"] == "B"


class TestEnvironmentAgentRemoteStubs:
    def test_agent_remote_factory(self):
        agent = EnvironmentAgent.remote(
            url="ws://localhost:8765", auth_token="secret"
        )
        assert agent is not None

    def test_agent_serve_factory(self):
        agent = EnvironmentAgent.serve(
            host="0.0.0.0", port=8080, workdir="/tmp"
        )
        assert agent is not None
