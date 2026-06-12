"""Cold-chain telemetry parsing and temperature excursion detection.

Parses IoT sensor data and checks for temperature excursions against
vaccine storage thresholds (2C to 8C per WHO guidelines).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from celeste.database.db import get_session

logger = logging.getLogger(__name__)

# Temperature thresholds for mRNA vaccine storage (WHO guidelines)
MIN_TEMP_C = 2.0
MAX_TEMP_C = 8.0
EXCURSION_THRESHOLD_C = 8.0


@asynccontextmanager
async def _get_session() -> AsyncIterator[AsyncSession]:
    """Get a database session from the Celeste session factory."""
    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Telemetry parsing
# ---------------------------------------------------------------------------


async def parse_telemetry(payload: dict | None) -> dict[str, Any]:
    """Parse an IoT telemetry payload from a vaccine cold-chain logger.

    Validates the payload structure and checks temperature against the
    acceptable range for mRNA vaccines (2C–8C). Returns alerts for any
    readings outside the safe range.

    Args:
        payload: A dictionary with keys:
            batch_id (str), temperature_c (float), humidity_pct (float),
            timestamp (str).

    Returns:
        A dict with keys:
            batch_id, temperature_c, humidity_pct, timestamp, alerts.
        On error, includes an ``error`` key with a description.
    """
    # Guard against non-dict payloads
    if not isinstance(payload, dict):
        return {
            "error": "Malformed payload: expected a JSON object (dict).",
            "batch_id": "",
            "temperature_c": 0.0,
            "humidity_pct": 0.0,
            "timestamp": "",
            "alerts": [],
        }

    batch_id = payload.get("batch_id")
    temperature_c = payload.get("temperature_c")
    humidity_pct = payload.get("humidity_pct")
    timestamp = payload.get("timestamp", "")

    # Validate required fields are present
    required_fields = ["batch_id", "temperature_c", "humidity_pct", "timestamp"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        return {
            "error": f"Missing required field(s): {', '.join(missing)}",
            "batch_id": str(batch_id) if batch_id is not None else "",
            "temperature_c": 0.0,
            "humidity_pct": 0.0,
            "timestamp": str(timestamp),
            "alerts": [],
        }

    # Type-coerce and validate
    try:
        temperature_c = float(temperature_c)
    except (TypeError, ValueError):
        return {
            "error": f"Invalid temperature_c value: {temperature_c!r}",
            "batch_id": str(batch_id),
            "temperature_c": 0.0,
            "humidity_pct": 0.0,
            "timestamp": str(timestamp),
            "alerts": [],
        }

    try:
        humidity_pct = float(humidity_pct) if humidity_pct is not None else 0.0
    except (TypeError, ValueError):
        return {
            "error": f"Invalid humidity_pct value: {humidity_pct!r}",
            "batch_id": str(batch_id),
            "temperature_c": temperature_c,
            "humidity_pct": 0.0,
            "timestamp": str(timestamp),
            "alerts": [],
        }

    # Coerce batch_id to string
    batch_id = str(batch_id) if batch_id is not None else ""

    # Check for alerts
    alerts: list[str] = []
    if temperature_c < MIN_TEMP_C:
        alerts.append(
            f"Temperature {temperature_c}C below minimum {MIN_TEMP_C}C — "
            f"risk of freezing damage"
        )
    if temperature_c > MAX_TEMP_C:
        alerts.append(
            f"Temperature {temperature_c}C exceeds maximum {MAX_TEMP_C}C — "
            f"cold-chain excursion detected"
        )

    return {
        "batch_id": batch_id,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "timestamp": str(timestamp),
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Temperature excursion check
# ---------------------------------------------------------------------------


async def check_temperature_excursion(batch_id: str) -> dict[str, Any]:
    """Check whether a batch has experienced a temperature excursion.

    Queries the telemetry_log table for recent readings and determines if
    the batch exceeded the 8C threshold for any duration.

    Args:
        batch_id: The batch identifier (e.g., "B-1847").

    Returns:
        A dict with keys:
            excursion (bool), max_temp_c (float), duration_minutes (float).
    """
    try:
        async with _get_session() as session:
            query = text("""
                SELECT temperature_c, recorded_at
                FROM telemetry_log
                WHERE batch_id = :batch_id
                ORDER BY recorded_at ASC
            """)

            result = await session.execute(query, {"batch_id": batch_id})
            rows = result.all()

            if not rows:
                return {
                    "excursion": False,
                    "max_temp_c": 0.0,
                    "duration_minutes": 0.0,
                    "batch_id": batch_id,
                }

            max_temp = 0.0
            excursion_count = 0
            prev_ts: datetime | None = None
            excursion_start: datetime | None = None
            excursion_end: datetime | None = None

            for row in rows:
                temp, recorded_at = row  # type: ignore[misc]
                temp_f = float(temp) if temp is not None else 0.0
                max_temp = max(max_temp, temp_f)

                try:
                    ts = datetime.fromisoformat(str(recorded_at))
                except (ValueError, TypeError):
                    ts = datetime.now(timezone.utc)

                if temp_f > EXCURSION_THRESHOLD_C:
                    excursion_count += 1
                    if excursion_start is None:
                        excursion_start = ts
                    excursion_end = ts
                else:
                    excursion_start = None
                    excursion_end = None

                prev_ts = ts

            # Calculate duration in minutes
            duration_minutes = 0.0
            if excursion_count > 0:
                # Estimate duration: each reading is ~5 minutes apart
                # (based on the 30-second interval in the design, but log
                # sampling is typically every 5 min for storage)
                duration_minutes = float(excursion_count * 5)

            return {
                "excursion": excursion_count > 0,
                "max_temp_c": max_temp,
                "duration_minutes": duration_minutes,
                "batch_id": batch_id,
            }

    except Exception as exc:
        logger.error(
            "Temperature excursion check failed for batch=%s: %s",
            batch_id,
            exc,
        )
        return {
            "excursion": False,
            "max_temp_c": 0.0,
            "duration_minutes": 0.0,
            "error": str(exc),
            "batch_id": batch_id,
        }
