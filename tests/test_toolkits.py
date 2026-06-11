"""
Tests for the pluggable toolkit interface and registries (Tasks 3.4-3.5).

Follows strict TDD: these tests are written BEFORE the implementation.
Covers:
- ToolParameter creation, validation, properties
- ToolDefinition creation and to_mcp_schema() output format
- BaseToolkit is abstract and cannot be instantiated directly
- SystemDataToolkit (core data tools)
- WebScrapingToolkit (web automation tools)
- CodingVerticalToolkit (software engineering plugin)
- MCP schema conformance
"""

from abc import ABC

import pytest

from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


# ===========================================================================
# ToolParameter
# ===========================================================================


class TestToolParameter:
    """ToolParameter data class tests."""

    def test_create_required_parameter(self):
        param = ToolParameter(
            name="path",
            type="string",
            description="File path",
            required=True,
        )
        assert param.name == "path"
        assert param.type == "string"
        assert param.description == "File path"
        assert param.required is True
        assert param.default is None
        assert param.enum is None

    def test_create_optional_parameter(self):
        param = ToolParameter(
            name="pattern",
            type="string",
            description="Glob pattern",
            required=False,
            default="*",
        )
        assert param.required is False
        assert param.default == "*"

    def test_create_parameter_with_enum(self):
        param = ToolParameter(
            name="mode",
            type="string",
            description="Access mode",
            required=True,
            enum=["read", "write", "append"],
        )
        assert param.enum == ["read", "write", "append"]

    def test_parameter_default_required_is_true(self):
        """If required is not specified, it defaults to True."""
        param = ToolParameter(
            name="path",
            type="string",
            description="File path",
        )
        assert param.required is True

    def test_parameter_default_default_is_none(self):
        param = ToolParameter(
            name="x",
            type="string",
            description="desc",
        )
        assert param.default is None

    def test_parameter_default_enum_is_none(self):
        param = ToolParameter(
            name="x",
            type="string",
            description="desc",
        )
        assert param.enum is None

    def test_parameter_valid_types(self):
        """All documented parameter types should be accepted."""
        valid_types = ["string", "integer", "boolean", "array", "object"]
        for t in valid_types:
            param = ToolParameter(name="p", type=t, description="desc")
            assert param.type == t


# ===========================================================================
# ToolDefinition
# ===========================================================================


class TestToolDefinition:
    """ToolDefinition data class and MCP schema tests."""

    def test_create_tool_definition(self):
        params = [
            ToolParameter(name="path", type="string", description="File path"),
        ]
        tool = ToolDefinition(
            name="read_file",
            description="Read file contents",
            parameters=params,
            returns="File contents as string",
        )
        assert tool.name == "read_file"
        assert tool.description == "Read file contents"
        assert len(tool.parameters) == 1
        assert tool.returns == "File contents as string"

    def test_to_mcp_schema_basic_structure(self):
        """MCP schema must have name, description, inputSchema."""
        params = [
            ToolParameter(name="path", type="string", description="File path"),
        ]
        tool = ToolDefinition(
            name="read_file",
            description="Read file contents",
            parameters=params,
            returns="File contents as string",
        )
        schema = tool.to_mcp_schema()

        assert "name" in schema
        assert "description" in schema
        assert "inputSchema" in schema
        assert schema["name"] == "read_file"
        assert schema["description"] == "Read file contents"

    def test_to_mcp_schema_input_schema_format(self):
        """inputSchema must follow JSON Schema object format."""
        params = [
            ToolParameter(
                name="path", type="string", description="File path", required=True
            ),
            ToolParameter(
                name="encoding",
                type="string",
                description="File encoding",
                required=False,
                default="utf-8",
            ),
        ]
        tool = ToolDefinition(
            name="read_file",
            description="Read file contents",
            parameters=params,
            returns="File contents as string",
        )
        schema = tool.to_mcp_schema()
        input_schema = schema["inputSchema"]

        assert input_schema["type"] == "object"
        assert "properties" in input_schema
        assert "path" in input_schema["properties"]
        assert "encoding" in input_schema["properties"]
        assert input_schema["properties"]["path"]["type"] == "string"
        assert input_schema["properties"]["path"]["description"] == "File path"
        assert input_schema["properties"]["encoding"]["default"] == "utf-8"

    def test_to_mcp_schema_required_fields(self):
        """Required parameters appear in the required list."""
        params = [
            ToolParameter(name="path", type="string", description="File path"),
            ToolParameter(
                name="encoding",
                type="string",
                description="File encoding",
                required=False,
            ),
        ]
        tool = ToolDefinition(
            name="read_file",
            description="Read file",
            parameters=params,
            returns="string",
        )
        schema = tool.to_mcp_schema()
        input_schema = schema["inputSchema"]

        assert "required" in input_schema
        assert "path" in input_schema["required"]
        assert "encoding" not in input_schema["required"]

    def test_to_mcp_schema_no_required_if_all_optional(self):
        """If all params are optional, required list should be empty or absent."""
        params = [
            ToolParameter(
                name="x", type="string", description="x", required=False
            ),
        ]
        tool = ToolDefinition(
            name="tool",
            description="desc",
            parameters=params,
            returns="string",
        )
        schema = tool.to_mcp_schema()
        input_schema = schema["inputSchema"]
        required = input_schema.get("required", [])
        assert required == [] or "x" not in required

    def test_to_mcp_schema_enum_in_properties(self):
        """Enum values should appear in the property definition."""
        params = [
            ToolParameter(
                name="mode",
                type="string",
                description="Mode",
                enum=["read", "write"],
            ),
        ]
        tool = ToolDefinition(
            name="set_mode",
            description="Set mode",
            parameters=params,
            returns="string",
        )
        schema = tool.to_mcp_schema()
        prop = schema["inputSchema"]["properties"]["mode"]
        assert prop["enum"] == ["read", "write"]

    def test_to_mcp_schema_no_parameters(self):
        """Tool with no parameters produces empty properties."""
        tool = ToolDefinition(
            name="noop",
            description="Does nothing",
            parameters=[],
            returns="None",
        )
        schema = tool.to_mcp_schema()
        assert schema["inputSchema"]["properties"] == {}


# ===========================================================================
# BaseToolkit (Abstract)
# ===========================================================================


class TestBaseToolkitAbstract:
    """BaseToolkit must be abstract and non-instantiable."""

    def test_is_abc_subclass(self):
        assert issubclass(BaseToolkit, ABC)

    def test_cannot_instantiate_directly(self):
        """BaseToolkit is abstract; instantiation must raise TypeError."""
        with pytest.raises(TypeError):
            BaseToolkit()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_abstract_methods(self):
        """A subclass that doesn't implement all abstracts can't be instantiated."""

        class IncompleteToolkit(BaseToolkit):
            pass

        with pytest.raises(TypeError):
            IncompleteToolkit()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self):
        """A subclass that implements all abstracts can be instantiated."""

        class DummyToolkit(BaseToolkit):
            @property
            def name(self) -> str:
                return "dummy"

            @property
            def description(self) -> str:
                return "A dummy toolkit"

            def get_tools(self):
                return []

            def get_tool(self, name: str):
                return None

            async def execute(self, name, arguments, driver):
                return {"success": True}

        tk = DummyToolkit()
        assert tk.name == "dummy"
        assert tk.description == "A dummy toolkit"
        assert tk.get_tools() == []
        assert tk.get_tool("anything") is None

    def test_to_mcp_schemas_default(self):
        """Default to_mcp_schemas should convert all tools to MCP schemas."""

        class DummyToolkit(BaseToolkit):
            @property
            def name(self) -> str:
                return "dummy"

            @property
            def description(self) -> str:
                return "A dummy toolkit"

            def get_tools(self):
                return [
                    ToolDefinition(
                        name="t1",
                        description="Tool 1",
                        parameters=[],
                        returns="None",
                    ),
                    ToolDefinition(
                        name="t2",
                        description="Tool 2",
                        parameters=[],
                        returns="None",
                    ),
                ]

            def get_tool(self, name: str):
                for t in self.get_tools():
                    if t.name == name:
                        return t
                return None

            async def execute(self, name, arguments, driver):
                return {"success": True}

        tk = DummyToolkit()
        schemas = tk.to_mcp_schemas()
        assert len(schemas) == 2
        assert schemas[0]["name"] == "t1"
        assert schemas[1]["name"] == "t2"


# ===========================================================================
# SystemDataToolkit
# ===========================================================================


class TestSystemDataToolkit:
    """Tests for the core data tools toolkit."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.system_data import SystemDataToolkit

        return SystemDataToolkit()

    def test_name(self, toolkit):
        assert toolkit.name == "system_data"

    def test_description(self, toolkit):
        assert isinstance(toolkit.description, str)
        assert len(toolkit.description) > 0

    def test_get_tools_returns_list(self, toolkit):
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_has_read_file(self, toolkit):
        tool = toolkit.get_tool("read_file")
        assert tool is not None
        assert tool.name == "read_file"
        assert "path" in [p.name for p in tool.parameters]

    def test_has_write_file(self, toolkit):
        tool = toolkit.get_tool("write_file")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names
        assert "content" in param_names

    def test_has_list_directory(self, toolkit):
        tool = toolkit.get_tool("list_directory")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names

    def test_has_parse_csv(self, toolkit):
        tool = toolkit.get_tool("parse_csv")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names

    def test_has_to_json(self, toolkit):
        tool = toolkit.get_tool("to_json")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "data" in param_names
        assert "path" in param_names

    def test_has_parse_json(self, toolkit):
        tool = toolkit.get_tool("parse_json")
        assert tool is not None
        assert "path" in [p.name for p in tool.parameters]

    def test_tool_count(self, toolkit):
        """SystemDataToolkit should have exactly 10 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 10

    def test_all_tools_have_names(self, toolkit):
        for tool in toolkit.get_tools():
            assert isinstance(tool.name, str)
            assert len(tool.name) > 0

    def test_all_tools_have_descriptions(self, toolkit):
        for tool in toolkit.get_tools():
            assert isinstance(tool.description, str)
            assert len(tool.description) > 0

    def test_all_tools_have_returns(self, toolkit):
        for tool in toolkit.get_tools():
            assert isinstance(tool.returns, str)
            assert len(tool.returns) > 0

    def test_all_tools_mcp_schemas_valid(self, toolkit):
        schemas = toolkit.to_mcp_schemas()
        assert len(schemas) == 10
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema
            assert schema["inputSchema"]["type"] == "object"
            assert "properties" in schema["inputSchema"]

    def test_read_file_path_required(self, toolkit):
        tool = toolkit.get_tool("read_file")
        path_param = [p for p in tool.parameters if p.name == "path"][0]
        assert path_param.required is True

    def test_list_directory_pattern_optional(self, toolkit):
        tool = toolkit.get_tool("list_directory")
        pattern_param = [p for p in tool.parameters if p.name == "pattern"]
        if pattern_param:
            assert pattern_param[0].required is False

    def test_parse_csv_delimiter_optional(self, toolkit):
        tool = toolkit.get_tool("parse_csv")
        delimiter_param = [p for p in tool.parameters if p.name == "delimiter"]
        if delimiter_param:
            assert delimiter_param[0].required is False

    def test_get_tool_returns_none_for_unknown(self, toolkit):
        assert toolkit.get_tool("nonexistent_tool") is None

    def test_all_tools_unique_names(self, toolkit):
        names = [t.name for t in toolkit.get_tools()]
        assert len(names) == len(set(names))


# ===========================================================================
# WebScrapingToolkit
# ===========================================================================


class TestWebScrapingToolkit:
    """Tests for the web automation tools toolkit."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        return WebScrapingToolkit()

    def test_name(self, toolkit):
        assert toolkit.name == "web_scraping"

    def test_description(self, toolkit):
        assert isinstance(toolkit.description, str)
        assert len(toolkit.description) > 0

    def test_has_http_get(self, toolkit):
        tool = toolkit.get_tool("http_get")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "url" in param_names

    def test_has_http_post(self, toolkit):
        tool = toolkit.get_tool("http_post")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "url" in param_names
        assert "body" in param_names

    def test_has_scrape_page(self, toolkit):
        tool = toolkit.get_tool("scrape_page")
        assert tool is not None
        assert "url" in [p.name for p in tool.parameters]

    def test_has_download_file(self, toolkit):
        tool = toolkit.get_tool("download_file")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "url" in param_names
        assert "destination" in param_names

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 4

    def test_http_get_headers_optional(self, toolkit):
        tool = toolkit.get_tool("http_get")
        headers_param = [p for p in tool.parameters if p.name == "headers"]
        if headers_param:
            assert headers_param[0].required is False

    def test_http_post_headers_optional(self, toolkit):
        tool = toolkit.get_tool("http_post")
        headers_param = [p for p in tool.parameters if p.name == "headers"]
        if headers_param:
            assert headers_param[0].required is False

    def test_scrape_page_selector_optional(self, toolkit):
        tool = toolkit.get_tool("scrape_page")
        selector_param = [p for p in tool.parameters if p.name == "selector"]
        if selector_param:
            assert selector_param[0].required is False

    def test_all_tools_mcp_schemas_valid(self, toolkit):
        schemas = toolkit.to_mcp_schemas()
        assert len(schemas) == 4
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema
            assert schema["inputSchema"]["type"] == "object"
            assert "properties" in schema["inputSchema"]

    def test_get_tool_returns_none_for_unknown(self, toolkit):
        assert toolkit.get_tool("nonexistent") is None

    def test_all_tools_unique_names(self, toolkit):
        names = [t.name for t in toolkit.get_tools()]
        assert len(names) == len(set(names))


# ===========================================================================
# CodingVerticalToolkit
# ===========================================================================


class TestCodingVerticalToolkit:
    """Tests for the software engineering plugin toolkit."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit

        return CodingVerticalToolkit()

    def test_name(self, toolkit):
        assert toolkit.name == "coding_vertical"

    def test_description(self, toolkit):
        assert isinstance(toolkit.description, str)
        assert len(toolkit.description) > 0

    def test_has_git_status(self, toolkit):
        tool = toolkit.get_tool("git_status")
        assert tool is not None
        assert "path" in [p.name for p in tool.parameters]

    def test_has_git_diff(self, toolkit):
        tool = toolkit.get_tool("git_diff")
        assert tool is not None
        assert "path" in [p.name for p in tool.parameters]

    def test_has_run_tests(self, toolkit):
        tool = toolkit.get_tool("run_tests")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names
        assert "command" in param_names

    def test_has_lint_code(self, toolkit):
        tool = toolkit.get_tool("lint_code")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names
        assert "command" in param_names

    def test_has_install_dependencies(self, toolkit):
        tool = toolkit.get_tool("install_dependencies")
        assert tool is not None
        param_names = [p.name for p in tool.parameters]
        assert "path" in param_names
        assert "command" in param_names

    def test_tool_count(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 5

    def test_git_diff_staged_optional(self, toolkit):
        tool = toolkit.get_tool("git_diff")
        staged_param = [p for p in tool.parameters if p.name == "staged"]
        if staged_param:
            assert staged_param[0].required is False

    def test_all_tools_mcp_schemas_valid(self, toolkit):
        schemas = toolkit.to_mcp_schemas()
        assert len(schemas) == 5
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema
            assert schema["inputSchema"]["type"] == "object"
            assert "properties" in schema["inputSchema"]

    def test_get_tool_returns_none_for_unknown(self, toolkit):
        assert toolkit.get_tool("nonexistent") is None

    def test_all_tools_unique_names(self, toolkit):
        names = [t.name for t in toolkit.get_tools()]
        assert len(names) == len(set(names))


# ===========================================================================
# Toolkit execute() via driver
# ===========================================================================


class MockDriver:
    """Fake driver for testing toolkit execute() methods."""

    def __init__(self, files=None, dirs=None, command_results=None, stat_results=None):
        self._files = files or {}
        self._dirs = dirs or {}
        self._command_results = command_results or {}
        self._stat_results = stat_results or {}

    async def read_file(self, path: str) -> dict:
        if path in self._files:
            content = self._files[path]
            return {"content": content, "size": len(content)}
        raise FileNotFoundError(path)

    async def list_directory(self, path: str) -> dict:
        if path in self._dirs:
            return {"files": list(self._dirs[path])}
        return {"files": []}

    async def run_command(self, command: str, args=None, cwd=None, timeout=None) -> dict:
        key = command + " " + " ".join(args or [])
        if key in self._command_results:
            return self._command_results[key]
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    async def stat(self, path: str) -> dict:
        if path in self._stat_results:
            return self._stat_results[path]
        return {"size": 0, "modified_time": None, "permissions": None}


class TestSystemDataToolkitExecute:
    """Tests for SystemDataToolkit.execute() via driver."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.system_data import SystemDataToolkit

        return SystemDataToolkit()

    @pytest.fixture()
    def driver(self):
        return MockDriver(
            files={"/tmp/test.txt": "hello world"},
            dirs={"/tmp": ["test.txt", "other.py"]},
            command_results={"echo hello": {"exit_code": 0, "stdout": "hello", "stderr": ""}},
            stat_results={"/tmp/test.txt": {"size": 11, "modified_time": 1234567890.0, "permissions": "644"}},
        )

    @pytest.mark.asyncio
    async def test_system_data_toolkit_read_file(self, toolkit, driver):
        result = await toolkit.execute("read_file", {"path": "/tmp/test.txt"}, driver)
        assert result["content"] == "hello world"
        assert result["size"] == 11

    @pytest.mark.asyncio
    async def test_system_data_toolkit_list_directory(self, toolkit, driver):
        result = await toolkit.execute("list_directory", {"path": "/tmp"}, driver)
        assert "files" in result
        assert "test.txt" in result["files"]
        assert "other.py" in result["files"]

    @pytest.mark.asyncio
    async def test_system_data_toolkit_run_command(self, toolkit, driver):
        result = await toolkit.execute(
            "run_command",
            {"command": "echo", "args": ["hello"]},
            driver,
        )
        assert result["exit_code"] == 0
        assert result["stdout"] == "hello"

    @pytest.mark.asyncio
    async def test_system_data_toolkit_snapshot(self, toolkit, driver):
        result = await toolkit.execute("snapshot", {"paths": ["/tmp"]}, driver)
        assert "files" in result
        assert result["platform"] in ("darwin", "linux", "win32", "")
        # snapshot should walk directories
        assert isinstance(result["files"], dict)

    @pytest.mark.asyncio
    async def test_system_data_toolkit_check_command(self, toolkit, driver):
        driver_with_which = MockDriver(
            command_results={
                "which python": {"exit_code": 0, "stdout": "/usr/bin/python", "stderr": ""},
            },
        )
        result = await toolkit.execute("check_command", {"command": "python"}, driver_with_which)
        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_system_data_toolkit_stat(self, toolkit, driver):
        result = await toolkit.execute("stat", {"path": "/tmp/test.txt"}, driver)
        assert result["size"] == 11
        assert result["modified_time"] == 1234567890.0
        assert result["permissions"] == "644"

    @pytest.mark.asyncio
    async def test_system_data_toolkit_unknown_tool(self, toolkit, driver):
        result = await toolkit.execute("nonexistent", {}, driver)
        assert "error" in result
        assert result["error"] == "tool_not_found"


class TestWebScrapingToolkitExecute:
    """Tests for WebScrapingToolkit.execute() via driver."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        return WebScrapingToolkit()

    @pytest.mark.asyncio
    async def test_web_scraping_toolkit_http_get(self, toolkit):
        import httpx

        # Mock the HTTP call by patching httpx.AsyncClient.get
        class FakeResponse:
            status_code = 200
            text = "<html>hello</html>"

        original_get = httpx.AsyncClient.get

        async def fake_get(*args, **kwargs):
            return FakeResponse()

        httpx.AsyncClient.get = fake_get
        try:
            result = await toolkit.execute("http_get", {"url": "https://example.com"}, None)
            assert result["status"] == 200
            assert result["body"] == "<html>hello</html>"
        finally:
            httpx.AsyncClient.get = original_get

    @pytest.mark.asyncio
    async def test_web_scraping_toolkit_unknown_tool(self, toolkit):
        result = await toolkit.execute("nonexistent", {}, None)
        assert "error" in result
        assert result["error"] == "tool_not_found"


class TestCodingVerticalToolkitExecute:
    """Tests for CodingVerticalToolkit.execute() via driver."""

    @pytest.fixture()
    def toolkit(self):
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit

        return CodingVerticalToolkit()

    @pytest.mark.asyncio
    async def test_coding_vertical_toolkit_execute(self, toolkit):
        result = await toolkit.execute("git_status", {"path": "/tmp"}, None)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_coding_vertical_toolkit_unknown_tool(self, toolkit):
        result = await toolkit.execute("nonexistent", {}, None)
        assert "error" in result
        assert result["error"] == "tool_not_found"


# ===========================================================================
# Cross-toolkit integration
# ===========================================================================


class TestCrossToolkitIntegration:
    """Cross-cutting concerns across all toolkits."""

    def test_all_toolkit_names_are_unique(self):
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste.toolkits.system_data import SystemDataToolkit
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        toolkits = [SystemDataToolkit(), WebScrapingToolkit(), CodingVerticalToolkit()]
        names = [tk.name for tk in toolkits]
        assert len(names) == len(set(names))

    def test_all_toolkits_subclass_base(self):
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste.toolkits.system_data import SystemDataToolkit
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        assert issubclass(SystemDataToolkit, BaseToolkit)
        assert issubclass(WebScrapingToolkit, BaseToolkit)
        assert issubclass(CodingVerticalToolkit, BaseToolkit)

    def test_all_tool_names_are_unique_across_toolkits(self):
        """No two toolkits should register a tool with the same name."""
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste.toolkits.system_data import SystemDataToolkit
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        all_names = []
        for TK in [SystemDataToolkit, WebScrapingToolkit, CodingVerticalToolkit]:
            tk = TK()
            all_names.extend(t.name for t in tk.get_tools())
        assert len(all_names) == len(set(all_names))

    def test_all_mcp_schemas_across_toolkits(self):
        """Every MCP schema across all toolkits is valid."""
        from celeste.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste.toolkits.system_data import SystemDataToolkit
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        for TK in [SystemDataToolkit, WebScrapingToolkit, CodingVerticalToolkit]:
            tk = TK()
            for schema in tk.to_mcp_schemas():
                assert isinstance(schema["name"], str)
                assert isinstance(schema["description"], str)
                assert isinstance(schema["inputSchema"], dict)
                assert schema["inputSchema"]["type"] == "object"
                assert isinstance(schema["inputSchema"]["properties"], dict)
