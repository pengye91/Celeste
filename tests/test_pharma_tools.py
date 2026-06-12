"""Tests for the pharma cold-chain custom tools.

Follows strict TDD. Covers:
- gdp_compliance: valid batch check, DB error handling
- customs_bridge: 503 retry with exponential backoff, fallback to cache
- cold_chain: normal telemetry parsing, malformed payload handling,
  temperature excursion check
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_cm(mock_session: AsyncMock) -> AsyncMock:
    """Configure an AsyncMock to act as an async context manager that
    returns itself on __aenter__."""
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    return mock_session


# ---------------------------------------------------------------------------
# GDP Compliance Tests
# ---------------------------------------------------------------------------


class TestGdpCompliance:
    """Tests for check_batch_gdp_compliance."""

    @pytest.mark.asyncio
    async def test_gdp_compliance_valid_batch(self):
        """Valid batch_id in a qualified hub returns qualified=True."""
        from examples.pharma_coldchain.tools.gdp_compliance import (
            check_batch_gdp_compliance,
        )

        # Mock the database session
        mock_session = _make_async_cm(AsyncMock())
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (
            "B-1840",            # batch_id
            "Amsterdam Hub",     # hub_name
            1,                   # qualified
            "Netherlands",       # country
        )
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "examples.pharma_coldchain.tools.gdp_compliance._get_session",
            return_value=mock_session,
        ):
            result = await check_batch_gdp_compliance(
                batch_id="B-1840", country="Netherlands",
            )

        assert result["qualified"] is True
        assert any("Netherlands GDP" in r for r in result["requirements"])
        assert result.get("warnings", []) == []

    @pytest.mark.asyncio
    async def test_gdp_compliance_batch_not_found(self):
        """Non-existent batch_id returns structured error with qualified=False."""
        from examples.pharma_coldchain.tools.gdp_compliance import (
            check_batch_gdp_compliance,
        )

        mock_session = _make_async_cm(AsyncMock())
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "examples.pharma_coldchain.tools.gdp_compliance._get_session",
            return_value=mock_session,
        ):
            result = await check_batch_gdp_compliance(
                batch_id="B-9999", country="Netherlands",
            )

        assert result["qualified"] is False
        assert "not found" in result["error"].lower()
        assert len(result["requirements"]) == 0

    @pytest.mark.asyncio
    async def test_gdp_compliance_unqualified_hub(self):
        """Batch at an unqualified hub returns qualified=False with warnings."""
        from examples.pharma_coldchain.tools.gdp_compliance import (
            check_batch_gdp_compliance,
        )

        mock_session = _make_async_cm(AsyncMock())
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = (
            "B-1843",      # batch_id
            "Lagos Hub",   # hub_name
            0,             # qualified (not qualified)
            "Nigeria",     # country
        )
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "examples.pharma_coldchain.tools.gdp_compliance._get_session",
            return_value=mock_session,
        ):
            result = await check_batch_gdp_compliance(
                batch_id="B-1843", country="Nigeria",
            )

        assert result["qualified"] is False
        assert len(result["warnings"]) > 0
        assert any("not qualified" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_gdp_compliance_db_error(self):
        """Database error raises a structured error dict, not an exception."""
        from examples.pharma_coldchain.tools.gdp_compliance import (
            check_batch_gdp_compliance,
        )

        mock_session = _make_async_cm(AsyncMock())
        mock_session.execute = AsyncMock(
            side_effect=RuntimeError("DB connection lost"),
        )

        with patch(
            "examples.pharma_coldchain.tools.gdp_compliance._get_session",
            return_value=mock_session,
        ):
            result = await check_batch_gdp_compliance(
                batch_id="B-1840", country="Netherlands",
            )

        assert result["qualified"] is False
        assert "error" in result
        assert "DB connection lost" in result["error"]


# ---------------------------------------------------------------------------
# Cold Chain Tests
# ---------------------------------------------------------------------------


class TestColdChainTelemetry:
    """Tests for parse_telemetry."""

    @pytest.mark.asyncio
    async def test_cold_chain_normal_telemetry(self):
        """Valid telemetry payload is parsed correctly with no alerts."""
        from examples.pharma_coldchain.tools.cold_chain import parse_telemetry

        payload = {
            "batch_id": "B-1840",
            "temperature_c": 2.8,
            "humidity_pct": 45.0,
            "timestamp": "2026-06-12T10:30:00Z",
        }

        result = await parse_telemetry(payload)

        assert result["batch_id"] == "B-1840"
        assert result["temperature_c"] == 2.8
        assert result["humidity_pct"] == 45.0
        assert result["timestamp"] == "2026-06-12T10:30:00Z"
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_cold_chain_temperature_alert(self):
        """Temperature outside 2C-8C range generates an alert."""
        from examples.pharma_coldchain.tools.cold_chain import parse_telemetry

        payload = {
            "batch_id": "B-1847",
            "temperature_c": 12.5,
            "humidity_pct": 55.0,
            "timestamp": "2026-06-12T10:35:00Z",
        }

        result = await parse_telemetry(payload)

        assert result["batch_id"] == "B-1847"
        assert len(result["alerts"]) > 0
        assert any("temperature" in a.lower() for a in result["alerts"])

    @pytest.mark.asyncio
    async def test_cold_chain_missing_field(self):
        """Payload missing required field returns error response."""
        from examples.pharma_coldchain.tools.cold_chain import parse_telemetry

        payload = {
            "batch_id": "B-1840",
            # missing temperature_c and humidity_pct
            "timestamp": "2026-06-12T10:30:00Z",
        }

        result = await parse_telemetry(payload)

        assert "error" in result
        assert result["batch_id"] == "B-1840"
        assert "missing" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cold_chain_malformed_payload(self):
        """Malformed payload (non-dict) returns error response."""
        from examples.pharma_coldchain.tools.cold_chain import parse_telemetry

        result = await parse_telemetry(None)  # type: ignore[arg-type]

        assert "error" in result
        assert "malformed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cold_chain_disconnect(self):
        """Malformed payload with wrong types returns error, not crash."""
        from examples.pharma_coldchain.tools.cold_chain import parse_telemetry

        payload = {
            "batch_id": 12345,  # should be a string
            "temperature_c": "not-a-number",
            "humidity_pct": None,
            "timestamp": "2026-06-12T10:30:00Z",
        }

        result = await parse_telemetry(payload)

        assert "error" in result
        # Should not crash but return structured error
        assert isinstance(result, dict)


class TestTemperatureExcursion:
    """Tests for check_temperature_excursion."""

    @pytest.mark.asyncio
    async def test_check_temperature_excursion_no_excursion(self):
        """Batch with normal temperatures returns excursion=False."""
        from examples.pharma_coldchain.tools.cold_chain import (
            check_temperature_excursion,
        )

        mock_session = _make_async_cm(AsyncMock())
        # Mock telemetry query results: all normal temps
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (2.8, "2026-06-12T10:00:00"),
            (3.1, "2026-06-12T10:05:00"),
            (2.9, "2026-06-12T10:10:00"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "examples.pharma_coldchain.tools.cold_chain._get_session",
            return_value=mock_session,
        ):
            result = await check_temperature_excursion(batch_id="B-1840")

        assert result["excursion"] is False
        assert result["max_temp_c"] == 3.1
        assert result["duration_minutes"] == 0

    @pytest.mark.asyncio
    async def test_check_temperature_excursion_detected(self):
        """Batch with temperature > 8C returns excursion=True."""
        from examples.pharma_coldchain.tools.cold_chain import (
            check_temperature_excursion,
        )

        mock_session = _make_async_cm(AsyncMock())
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (2.8, "2026-06-12T10:00:00"),
            (8.5, "2026-06-12T10:05:00"),
            (9.2, "2026-06-12T10:10:00"),
            (8.8, "2026-06-12T10:15:00"),
            (3.1, "2026-06-12T10:20:00"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "examples.pharma_coldchain.tools.cold_chain._get_session",
            return_value=mock_session,
        ):
            result = await check_temperature_excursion(batch_id="B-1847")

        assert result["excursion"] is True
        assert result["max_temp_c"] == 9.2
        assert result["duration_minutes"] == 15.0  # 3 readings × 5 min

    @pytest.mark.asyncio
    async def test_check_temperature_excursion_db_error(self):
        """Database error returns structured error with excursion=False."""
        from examples.pharma_coldchain.tools.cold_chain import (
            check_temperature_excursion,
        )

        mock_session = _make_async_cm(AsyncMock())
        mock_session.execute = AsyncMock(
            side_effect=RuntimeError("DB connection lost"),
        )

        with patch(
            "examples.pharma_coldchain.tools.cold_chain._get_session",
            return_value=mock_session,
        ):
            result = await check_temperature_excursion(batch_id="B-1840")

        assert "error" in result
        assert result["excursion"] is False


# ---------------------------------------------------------------------------
# Customs Bridge Tests
# ---------------------------------------------------------------------------


class TestCustomsBridge:
    """Tests for check_import_rules."""

    @pytest.mark.asyncio
    async def test_customs_bridge_valid_country(self):
        """Valid country returns import rules without retries."""
        from examples.pharma_coldchain.tools.customs_bridge import (
            check_import_rules,
        )

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "country": "NG",
            "rules": [
                {"rule": "GDP Certificate required", "code": "NG-GDP-001"},
                {"rule": "Temperature log mandatory", "code": "NG-TEMP-001"},
            ],
            "tariff_pct": 5.0,
        }
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        # Configure as async context manager
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch(
            "examples.pharma_coldchain.tools.customs_bridge.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await check_import_rules(country="NG")

        assert "rules" in result
        assert len(result["rules"]) == 2
        assert result.get("from_cache") is False
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_customs_bridge_unknown_country(self):
        """Unknown country returns empty rule set."""
        from examples.pharma_coldchain.tools.customs_bridge import (
            check_import_rules,
        )

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "No rules for country XX"}
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch(
            "examples.pharma_coldchain.tools.customs_bridge.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await check_import_rules(country="XX")

        assert result.get("rules", []) == []
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_customs_bridge_503_retry(self):
        """503 twice then success: retry works and returns real data."""
        from examples.pharma_coldchain.tools.customs_bridge import (
            check_import_rules,
        )

        mock_client = AsyncMock()
        fail_response = MagicMock()
        fail_response.status_code = 503
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "country": "KE",
            "rules": [{"rule": "Import permit required", "code": "KE-IMP-001"}],
            "tariff_pct": 2.5,
        }
        mock_client.get = AsyncMock(
            side_effect=[fail_response, fail_response, success_response],
        )
        mock_client.aclose = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch(
            "examples.pharma_coldchain.tools.customs_bridge.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await check_import_rules(country="KE")

        assert "rules" in result
        assert len(result["rules"]) == 1
        assert result.get("from_cache") is False
        assert mock_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_customs_bridge_fallback(self):
        """503 three times triggers fallback to cached data."""
        from examples.pharma_coldchain.tools.customs_bridge import (
            check_import_rules,
        )

        # Create a temporary fallback tariffs JSON file
        import tempfile

        fallback_data = {
            "NG": {
                "country": "NG",
                "rules": [
                    {"rule": "GDP Certificate required", "code": "NG-GDP-001"},
                ],
                "tariff_pct": 5.0,
                "cached": True,
            },
            "KE": {
                "country": "KE",
                "rules": [
                    {"rule": "Import permit required", "code": "KE-IMP-001"},
                ],
                "tariff_pct": 2.5,
                "cached": True,
            },
        }

        tmpdir = Path(tempfile.mkdtemp())
        seed_dir = tmpdir / "seed_data"
        seed_dir.mkdir()
        fallback_path = seed_dir / "fallback_tariffs.json"
        fallback_path.write_text(json.dumps(fallback_data))

        mock_client = AsyncMock()
        fail_response = MagicMock()
        fail_response.status_code = 503
        mock_client.get = AsyncMock(
            side_effect=[fail_response, fail_response, fail_response],
        )
        mock_client.aclose = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch(
            "examples.pharma_coldchain.tools.customs_bridge.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with patch(
                "examples.pharma_coldchain.tools.customs_bridge._FALLBACK_PATH",
                fallback_path,
            ):
                result = await check_import_rules(country="KE")

        assert "rules" in result
        assert result.get("from_cache") is True
        assert mock_client.get.call_count == 3

        # Clean up
        import shutil
        shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_customs_bridge_no_fallback_available(self):
        """All retries exhausted and no cache returns error with warning."""
        from examples.pharma_coldchain.tools.customs_bridge import (
            check_import_rules,
        )

        import tempfile

        tmpdir = Path(tempfile.mkdtemp())
        seed_dir = tmpdir / "seed_data"
        seed_dir.mkdir()
        # No fallback file exists

        mock_client = AsyncMock()
        fail_response = MagicMock()
        fail_response.status_code = 503
        mock_client.get = AsyncMock(
            side_effect=[fail_response, fail_response, fail_response],
        )
        mock_client.aclose = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        with patch(
            "examples.pharma_coldchain.tools.customs_bridge.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with patch(
                "examples.pharma_coldchain.tools.customs_bridge._FALLBACK_PATH",
                seed_dir / "fallback_tariffs.json",
            ):
                result = await check_import_rules(country="ZZ")

        assert "error" in result
        assert result.get("rules", []) == []

        import shutil
        shutil.rmtree(tmpdir)


# ---------------------------------------------------------------------------
# PharmaColdChainToolkit Tests
# ---------------------------------------------------------------------------


class TestPharmaColdChainToolkit:
    """Tests for PharmaColdChainToolkit (tool registry and execute dispatch)."""

    @pytest.fixture
    def toolkit(self):
        from examples.pharma_coldchain.tools.pharma_toolkit import (
            PharmaColdChainToolkit,
        )

        return PharmaColdChainToolkit()

    def test_get_tools_returns_all_four(self, toolkit):
        """get_tools() must return exactly the four registered pharma tools."""
        tools = toolkit.get_tools()

        assert len(tools) == 4
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "parse_telemetry",
            "check_temperature_excursion",
            "check_import_rules",
            "check_batch_gdp_compliance",
        }

    def test_get_tool_returns_by_name(self, toolkit):
        """get_tool() must return the correct ToolDefinition for a given name."""
        tool = toolkit.get_tool("parse_telemetry")

        assert tool is not None
        assert tool.name == "parse_telemetry"
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "payload"

    def test_get_tool_returns_none_for_unknown_name(self, toolkit):
        """get_tool() must return None when the tool name is not registered."""
        tool = toolkit.get_tool("nonexistent_tool")
        assert tool is None

    def test_toolkit_name_and_description(self, toolkit):
        """PharmaColdChainToolkit must expose name and description properties."""
        assert toolkit.name == "pharma_coldchain"
        assert "cold-chain" in toolkit.description.lower()

    @pytest.mark.asyncio
    async def test_execute_dispatches_parse_telemetry(self, toolkit):
        """execute('parse_telemetry', ...) must dispatch to parse_telemetry."""
        payload = {
            "batch_id": "B-1840",
            "temperature_c": 2.8,
            "humidity_pct": 45.0,
            "timestamp": "2026-06-12T10:30:00Z",
        }

        with patch(
            "examples.pharma_coldchain.tools.pharma_toolkit.parse_telemetry",
            new_callable=AsyncMock,
        ) as mock_fn:
            mock_fn.return_value = {"batch_id": "B-1840", "alerts": []}
            result = await toolkit.execute(
                "parse_telemetry",
                {"payload": payload},
                driver=None,
            )

        assert result["batch_id"] == "B-1840"
        mock_fn.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_execute_dispatches_check_temperature_excursion(self, toolkit):
        """execute('check_temperature_excursion', ...) must dispatch correctly."""
        with patch(
            "examples.pharma_coldchain.tools.pharma_toolkit.check_temperature_excursion",
            new_callable=AsyncMock,
        ) as mock_fn:
            mock_fn.return_value = {
                "excursion": False,
                "max_temp_c": 3.1,
                "duration_minutes": 0,
            }
            result = await toolkit.execute(
                "check_temperature_excursion",
                {"batch_id": "B-1840"},
                driver=None,
            )

        assert result["excursion"] is False
        mock_fn.assert_called_once_with("B-1840")

    @pytest.mark.asyncio
    async def test_execute_dispatches_check_import_rules(self, toolkit):
        """execute('check_import_rules', ...) must dispatch correctly."""
        with patch(
            "examples.pharma_coldchain.tools.pharma_toolkit.check_import_rules",
            new_callable=AsyncMock,
        ) as mock_fn:
            mock_fn.return_value = {
                "rules": [{"rule": "GDP Certificate required"}],
                "from_cache": False,
            }
            result = await toolkit.execute(
                "check_import_rules",
                {"country": "NG"},
                driver=None,
            )

        assert result["from_cache"] is False
        mock_fn.assert_called_once_with("NG")

    @pytest.mark.asyncio
    async def test_execute_dispatches_check_batch_gdp_compliance(self, toolkit):
        """execute('check_batch_gdp_compliance', ...) must dispatch correctly."""
        with patch(
            "examples.pharma_coldchain.tools.pharma_toolkit.check_batch_gdp_compliance",
            new_callable=AsyncMock,
        ) as mock_fn:
            mock_fn.return_value = {
                "qualified": True,
                "batch_id": "B-1840",
            }
            result = await toolkit.execute(
                "check_batch_gdp_compliance",
                {"batch_id": "B-1840", "country": "Netherlands"},
                driver=None,
            )

        assert result["qualified"] is True
        mock_fn.assert_called_once_with("B-1840", "Netherlands")

    @pytest.mark.asyncio
    async def test_execute_returns_error_for_unknown_tool(self, toolkit):
        """execute() must return a structured error for an unknown tool name."""
        result = await toolkit.execute(
            "nonexistent_tool",
            {"some_arg": "value"},
            driver=None,
        )

        assert "error" in result
        assert result["error"] == "tool_not_found"
        assert result["tool_name"] == "nonexistent_tool"
