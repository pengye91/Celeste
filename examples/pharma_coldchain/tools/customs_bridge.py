"""Customs bridge for pharmaceutical import rules.

Queries a real (or mocked) customs API for country-specific import rules
with intelligent retry and fallback to cached data.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Maximum number of retry attempts on 503
_MAX_RETRIES = 3

# Base backoff in seconds (exponential: 1, 2, 4, ...)
_BASE_BACKOFF_S = 1.0

# Path to fallback tariffs JSON — can be overridden for testing
_FALLBACK_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "pharma-coldchain"
    / "seed_data"
    / "fallback_tariffs.json"
)


async def _fetch_rules(client: httpx.AsyncClient, country: str) -> dict[str, Any]:
    """Make a single HTTP GET to the customs API."""
    # In production this would be a real URL; in tests it is mocked
    url = f"http://localhost:8090/api/customs/rules/{country}"
    response = await client.get(url, timeout=10.0)
    if response.status_code == 200:
        data = response.json()
        data["from_cache"] = False
        return data
    if response.status_code == 404:
        return {
            "country": country,
            "rules": [],
            "tariff_pct": 0.0,
            "from_cache": False,
            "warning": f"No import rules found for country '{country}'.",
        }
    # Any other status code (including 503) will trigger a retry at the
    # call site.
    raise httpx.HTTPStatusError(
        f"Customs API returned {response.status_code} for country={country}",
        request=response.request,
        response=response,
    )


def _load_fallback(country: str) -> dict[str, Any] | None:
    """Load cached tariff data from the local fallback file."""
    try:
        if not _FALLBACK_PATH.exists():
            return None
        data = json.loads(_FALLBACK_PATH.read_text())
        entry = data.get(country)
        if entry is None:
            return None
        entry["from_cache"] = True
        return entry
    except Exception as exc:
        logger.warning("Failed to load fallback tariffs: %s", exc)
        return None


async def check_import_rules(country: str) -> dict[str, Any]:
    """Check pharmaceutical import rules for a destination country.

    Attempts up to 3 retries with exponential backoff on transient (503)
    errors. Falls back to locally cached tariff data if all retries are
    exhausted.

    Args:
        country: ISO 3166-1 alpha-2 country code (e.g., "NG", "KE").

    Returns:
        A dict with keys:
            rules (list[dict]): List of import rule objects.
            tariff_pct (float): Customs tariff percentage.
            from_cache (bool): True if data came from fallback cache.
    """
    async with httpx.AsyncClient() as client:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return await _fetch_rules(client, country)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503:
                    backoff = _BASE_BACKOFF_S * (2 ** (attempt - 1))
                    logger.warning(
                        "Customs API 503 for country=%s (attempt %d/%d), "
                        "retrying in %.1fs...",
                        country,
                        attempt,
                        _MAX_RETRIES,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                # Non-retryable error
                logger.error(
                    "Customs API unrecoverable error for country=%s: %s",
                    country,
                    exc,
                )
                return {
                    "country": country,
                    "rules": [],
                    "tariff_pct": 0.0,
                    "error": str(exc),
                    "from_cache": False,
                }
            except Exception as exc:
                logger.error(
                    "Customs API request failed for country=%s (attempt %d): %s",
                    country,
                    attempt,
                    exc,
                )
                if attempt < _MAX_RETRIES:
                    backoff = _BASE_BACKOFF_S * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)
                    continue
                # All retries exhausted for non-HTTP errors too
                break

    # All attempts failed — try fallback
    logger.warning(
        "All %d retries exhausted for country=%s, falling back to cached data.",
        _MAX_RETRIES,
        country,
    )
    fallback = _load_fallback(country)
    if fallback is not None:
        return fallback

    return {
        "country": country,
        "rules": [],
        "tariff_pct": 0.0,
        "error": (
            f"Customs API unavailable for country={country} after "
            f"{_MAX_RETRIES} retries. No cached fallback data available."
        ),
        "from_cache": False,
    }
