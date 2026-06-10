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

from celeste_dag.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


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
        from celeste_dag.toolkits.system_data import SystemDataToolkit

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
        """SystemDataToolkit should have exactly 6 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 6

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
        assert len(schemas) == 6
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
        from celeste_dag.toolkits.web_scraping import WebScrapingToolkit

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
        from celeste_dag.toolkits.coding_vertical import CodingVerticalToolkit

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
# Cross-toolkit integration
# ===========================================================================


class TestCrossToolkitIntegration:
    """Cross-cutting concerns across all toolkits."""

    def test_all_toolkit_names_are_unique(self):
        from celeste_dag.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste_dag.toolkits.system_data import SystemDataToolkit
        from celeste_dag.toolkits.web_scraping import WebScrapingToolkit

        toolkits = [SystemDataToolkit(), WebScrapingToolkit(), CodingVerticalToolkit()]
        names = [tk.name for tk in toolkits]
        assert len(names) == len(set(names))

    def test_all_toolkits_subclass_base(self):
        from celeste_dag.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste_dag.toolkits.system_data import SystemDataToolkit
        from celeste_dag.toolkits.web_scraping import WebScrapingToolkit

        assert issubclass(SystemDataToolkit, BaseToolkit)
        assert issubclass(WebScrapingToolkit, BaseToolkit)
        assert issubclass(CodingVerticalToolkit, BaseToolkit)

    def test_all_tool_names_are_unique_across_toolkits(self):
        """No two toolkits should register a tool with the same name."""
        from celeste_dag.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste_dag.toolkits.system_data import SystemDataToolkit
        from celeste_dag.toolkits.web_scraping import WebScrapingToolkit

        all_names = []
        for TK in [SystemDataToolkit, WebScrapingToolkit, CodingVerticalToolkit]:
            tk = TK()
            all_names.extend(t.name for t in tk.get_tools())
        assert len(all_names) == len(set(all_names))

    def test_all_mcp_schemas_across_toolkits(self):
        """Every MCP schema across all toolkits is valid."""
        from celeste_dag.toolkits.coding_vertical import CodingVerticalToolkit
        from celeste_dag.toolkits.system_data import SystemDataToolkit
        from celeste_dag.toolkits.web_scraping import WebScrapingToolkit

        for TK in [SystemDataToolkit, WebScrapingToolkit, CodingVerticalToolkit]:
            tk = TK()
            for schema in tk.to_mcp_schemas():
                assert isinstance(schema["name"], str)
                assert isinstance(schema["description"], str)
                assert isinstance(schema["inputSchema"], dict)
                assert schema["inputSchema"]["type"] == "object"
                assert isinstance(schema["inputSchema"]["properties"], dict)
