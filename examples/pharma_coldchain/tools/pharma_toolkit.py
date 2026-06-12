"""Pharma Cold-Chain Toolkit — BaseToolkit wrapper for custom pharma tools.

Wraps the standalone async functions (GDP compliance, telemetry parsing,
temperature excursion detection, and customs import rules) so they can be
registered with the EnvironmentAgent via the standard toolkit interface.
"""

from __future__ import annotations

from typing import Any

from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter

from examples.pharma_coldchain.tools.cold_chain import (
    check_temperature_excursion,
    parse_telemetry,
)
from examples.pharma_coldchain.tools.customs_bridge import check_import_rules
from examples.pharma_coldchain.tools.gdp_compliance import check_batch_gdp_compliance


class PharmaColdChainToolkit(BaseToolkit):
    """Custom pharma cold-chain tools exposed as a Celeste toolkit.

    Provides:
    - parse_telemetry: Parse IoT sensor payloads and detect excursions
    - check_temperature_excursion: Query telemetry_log for batch excursion status
    - check_import_rules: Query customs API for country-specific import rules
    - check_batch_gdp_compliance: Verify GDP qualification for a batch/country pair
    """

    @property
    def name(self) -> str:
        return "pharma_coldchain"

    @property
    def description(self) -> str:
        return (
            "Pharma cold-chain tools for GDP compliance verification, "
            "temperature excursion detection, IoT telemetry parsing, "
            "and customs import rules with retry/fallback."
        )

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    _TOOLS: list[ToolDefinition] = [
        ToolDefinition(
            name="parse_telemetry",
            description=(
                "Parse an IoT telemetry payload from a vaccine cold-chain "
                "logger. Validates payload structure and checks temperature "
                "against the acceptable range for mRNA vaccines (2C–8C). "
                "Returns alerts for any readings outside the safe range."
            ),
            parameters=[
                ToolParameter(
                    name="payload",
                    type="object",
                    description=(
                        "Telemetry payload dict with keys: batch_id (str), "
                        "temperature_c (float), humidity_pct (float), "
                        "timestamp (str)."
                    ),
                    required=True,
                ),
            ],
            returns=(
                "Dict with keys: batch_id, temperature_c, humidity_pct, "
                "timestamp, alerts (list[str]). On error, includes an "
                "'error' key with a description."
            ),
        ),
        ToolDefinition(
            name="check_temperature_excursion",
            description=(
                "Check whether a vaccine batch has experienced a temperature "
                "excursion. Queries the telemetry_log table for recent "
                "readings and determines if the batch exceeded the 8C "
                "threshold for any duration."
            ),
            parameters=[
                ToolParameter(
                    name="batch_id",
                    type="string",
                    description="The batch identifier (e.g., 'B-1847').",
                    required=True,
                ),
            ],
            returns=(
                "Dict with keys: excursion (bool), max_temp_c (float), "
                "duration_minutes (float), batch_id (str)."
            ),
        ),
        ToolDefinition(
            name="check_import_rules",
            description=(
                "Check pharmaceutical import rules for a destination country. "
                "Attempts up to 3 retries with exponential backoff on "
                "transient (503) errors. Falls back to locally cached tariff "
                "data if all retries are exhausted."
            ),
            parameters=[
                ToolParameter(
                    name="country",
                    type="string",
                    description=(
                        "ISO 3166-1 alpha-2 country code (e.g., 'NG', 'KE')."
                    ),
                    required=True,
                ),
            ],
            returns=(
                "Dict with keys: rules (list[dict]), tariff_pct (float), "
                "from_cache (bool)."
            ),
        ),
        ToolDefinition(
            name="check_batch_gdp_compliance",
            description=(
                "Check whether a vaccine batch is GDP-compliant for a "
                "destination country. Queries the database for the batch "
                "and its hub qualification status, then checks against "
                "the country-specific GDP requirements."
            ),
            parameters=[
                ToolParameter(
                    name="batch_id",
                    type="string",
                    description="The batch identifier (e.g., 'B-1840').",
                    required=True,
                ),
                ToolParameter(
                    name="country",
                    type="string",
                    description="The destination country name.",
                    required=True,
                ),
            ],
            returns=(
                "Dict with keys: qualified (bool), requirements (list[str]), "
                "warnings (list[str]), batch_id, hub_name, country. "
                "On error, includes an 'error' key."
            ),
        ),
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        return list(self._TOOLS)

    def get_tool(self, name: str) -> ToolDefinition | None:
        for tool in self._TOOLS:
            if tool.name == name:
                return tool
        return None

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        driver: Any | None,  # noqa: ARG002 — required by BaseToolkit interface
    ) -> dict[str, Any]:
        """Execute a pharma cold-chain tool by name.

        These tools are self-contained (they manage their own DB sessions
        and HTTP clients) so the *driver* parameter is unused.
        """
        if name == "parse_telemetry":
            payload = arguments.get("payload")
            return await parse_telemetry(payload)

        if name == "check_temperature_excursion":
            batch_id = arguments.get("batch_id", "")
            return await check_temperature_excursion(str(batch_id))

        if name == "check_import_rules":
            country = arguments.get("country", "")
            return await check_import_rules(str(country))

        if name == "check_batch_gdp_compliance":
            batch_id = arguments.get("batch_id", "")
            country = arguments.get("country", "")
            return await check_batch_gdp_compliance(str(batch_id), str(country))

        return {"error": "tool_not_found", "tool_name": name}
