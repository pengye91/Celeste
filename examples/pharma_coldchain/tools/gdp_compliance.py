"""GDP (Good Distribution Practice) compliance tool for pharma cold-chain.

Checks whether a vaccine batch qualifies for distribution in a given country
based on hub qualifications and regulatory requirements.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from celeste.database.db import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database session helper
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _get_session() -> AsyncIterator[AsyncSession]:
    """Get a database session from the Celeste session factory."""
    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# GDP compliance rule sets by country
# ---------------------------------------------------------------------------

_COUNTRY_GDP_REQUIREMENTS: dict[str, list[str]] = {
    "Netherlands": [
        "Netherlands GDP Certificate (Annex 16)",
        "Temperature log 2C-8C for entire journey",
        "Batch release certificate from QP",
        "Serialization compliance (EU FMD)",
    ],
    "Germany": [
        "Germany GDP Certificate (AMG Section 13)",
        "Temperature log 2C-8C for entire journey",
        "Batch release certificate from QP",
        "German import notification (Section 72a AMG)",
    ],
    "France": [
        "France GDP Certificate (ANSM)",
        "Temperature log 2C-8C for entire journey",
        "Batch release certificate from QP",
        "French labelling requirements (CIP code)",
    ],
    "Nigeria": [
        "Nigeria GDP Certificate (NAFDAC)",
        "Temperature log 2C-8C for entire journey",
        "NAFDAC import permit",
        "Fumigation certificate",
        "Certificate of Pharmaceutical Product (COPP)",
    ],
    "Kenya": [
        "Kenya GDP Certificate (PPB)",
        "Temperature log 2C-8C for entire journey",
        "Kenya import permit",
        "Pre-shipment inspection certificate",
    ],
    "India": [
        "India GDP Certificate (CDSCO)",
        "Temperature log 2C-8C for entire journey",
        "CDSCO import license",
        "Batch testing at CDL Kolkata",
        "Customs clearance with port health officer",
    ],
}


def _get_requirements(country: str) -> list[str]:
    """Get the GDP compliance requirements for a given country."""
    return _COUNTRY_GDP_REQUIREMENTS.get(
        country,
        ["International GDP Certificate", "Temperature log 2C-8C"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_batch_gdp_compliance(batch_id: str, country: str) -> dict[str, Any]:
    """Check whether a vaccine batch is GDP-compliant for a destination country.

    Queries the database for the batch and its hub qualification status, then
    checks against the country-specific GDP requirements.

    Args:
        batch_id: The batch identifier (e.g., "B-1840").
        country: The destination country name.

    Returns:
        A dict with keys:
            - qualified (bool): Whether the batch qualifies.
            - requirements (list[str]): Country-specific GDP requirements.
            - warnings (list[str]): Any issues found.
            - error (str, optional): Present only if an error occurred.
    """
    try:
        async with _get_session() as session:
            query = text("""
                SELECT
                    b.batch_id,
                    h.name AS hub_name,
                    h.qualified,
                    h.country AS hub_country
                FROM batches b
                JOIN hubs h ON b.hub_id = h.id
                WHERE b.batch_id = :batch_id
            """)

            result = await session.execute(query, {"batch_id": batch_id})
            row = result.one_or_none()

            if row is None:
                return {
                    "qualified": False,
                    "requirements": [],
                    "warnings": [],
                    "error": f"Batch '{batch_id}' not found in database.",
                }

            batch_id_val, hub_name, qualified, hub_country = row  # type: ignore[misc]

            requirements = _get_requirements(country)
            warnings: list[str] = []

            # Check hub qualification
            if not qualified:
                warnings.append(
                    f"Hub '{hub_name}' (country: {hub_country}) is not qualified "
                    f"for GDP distribution."
                )

            # Check if hub country matches destination (cross-border may need extra docs)
            if hub_country != country:
                warnings.append(
                    f"Cross-border shipment: hub in {hub_country}, "
                    f"destination {country}. Additional import documentation required."
                )

            return {
                "qualified": bool(qualified) and country in _COUNTRY_GDP_REQUIREMENTS,
                "requirements": requirements,
                "warnings": warnings,
                "batch_id": batch_id_val,
                "hub_name": hub_name,
                "country": country,
            }

    except Exception as exc:
        logger.error(
            "GDP compliance check failed for batch=%s country=%s: %s",
            batch_id,
            country,
            exc,
        )
        return {
            "qualified": False,
            "requirements": [],
            "warnings": [],
            "error": str(exc),
        }
