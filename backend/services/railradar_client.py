"""
services/railradar_client.py

Centralized RailRadar API Client

Responsibilities
----------------
✓ Authentication
✓ Connection pooling
✓ Rate limiting
✓ Response caching
✓ Error handling
✓ Consistent response format
"""

import copy
import json
import logging
import os

import requests
from dotenv import load_dotenv

from services.cache import (
    cache,
    LIVE_STATUS_TTL,
    TRAIN_SEARCH_TTL,
    TRAIN_DETAILS_TTL,
    STATION_BOARD_TTL,
    ROUTE_TTL,
    LOOKUP_TTL,
)

from services.rate_limiter import rate_limiter

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = os.getenv(
    "RAILRADAR_BASE_URL",
    "https://api.railradar.in/v1"
).rstrip("/")

API_KEY = os.getenv("RAILRADAR_API_KEY")

TIMEOUT = int(
    os.getenv("RAILRADAR_TIMEOUT", "15")
)


class RailRadarClient:

    def __init__(self):

        if not API_KEY:
            raise ValueError(
                "RAILRADAR_API_KEY not found in environment."
            )

        self.base_url = BASE_URL

        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {API_KEY}",
            "Accept": "application/json",
            "User-Agent": "RailwayAssistantBot/1.0"
        })

    def _normalize_station_code_for_api(self, code: str) -> str:
        if not code:
            return code
        if code.upper() == "BCT":
            return "MMCT"
        return code.upper()

    def _cache_key(self, endpoint: str, params: dict | None = None) -> str:
        normalized_params = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
        return f"{endpoint}:{normalized_params}"

    ####################################################################
    # Generic GET Request
    ####################################################################

    def _request(
        self,
        endpoint: str,
        params: dict | None = None,
        ttl: int = 60
    ) -> dict:

        cache_key = self._cache_key(endpoint, params)

        # ---------------------------------------------------------------
        # Cache Lookup
        # ---------------------------------------------------------------

        cached = cache.get(cache_key)

        if cached is not None:

            logger.info(f"[CACHE HIT] {cache_key}")

            cached_response = copy.deepcopy(cached)
            cached_response["cached"] = True

            return cached_response

        try:

            # -----------------------------------------------------------
            # Local Rate Limiter
            # -----------------------------------------------------------

            rate_limiter.acquire()

            logger.info(f"[API REQUEST] {endpoint}")

            response = self.session.get(
                f"{self.base_url}{endpoint}",
                params=params,
                timeout=TIMEOUT
            )

            response.raise_for_status()

            try:
                payload = response.json()

            except ValueError:

                logger.error("Invalid JSON returned from RailRadar.")

                return {
                    "success": False,
                    "error": "Invalid JSON response from RailRadar.",
                    "status_code": 502
                }

            if payload.get("success", False):

                payload["cached"] = False

                cache.set(
                    cache_key,
                    copy.deepcopy(payload),
                    ttl
                )

                return payload

            return {
                "success": False,
                "error": payload.get(
                    "error",
                    payload.get(
                        "message",
                        "Unknown API Error"
                    )
                ),
                "status_code": response.status_code
            }

        except requests.exceptions.Timeout:

            logger.exception("RailRadar timeout")

            return {
                "success": False,
                "error": "RailRadar request timed out.",
                "status_code": 408
            }

        except requests.exceptions.HTTPError as e:

            

            status = e.response.status_code

            if status == 429:

                return {
                    "success": False,
                    "error": (
                        "RailRadar request limit has been reached. "
                        "Please wait about a minute before trying again."
                    ),
                    "status_code": 429
                }

            return {
                "success": False,
                "error": str(e),
                "status_code": status
            }

        except requests.exceptions.ConnectionError:

            logger.exception("RailRadar Connection Error")

            return {
                "success": False,
                "error": "Unable to connect to RailRadar API.",
                "status_code": 503
            }

        except Exception as e:

            logger.exception("Unexpected RailRadar Error")

            return {
                "success": False,
                "error": str(e),
                "status_code": 500
            }

    ####################################################################
    # API Endpoints
    ####################################################################

    def train_details(self, train_number: str):

        return self._request(
            f"/trains/{train_number}",
            ttl=3600
        )

    def live_status(self, train_number: str):

        return self._request(
            f"/trains/{train_number}/live",
            ttl=30
        )

    def trains_between(
        self,
        source: str,
        destination: str
    ):
        src = self._normalize_station_code_for_api(source)
        dst = self._normalize_station_code_for_api(destination)
        return self._request(
            f"/trains/between/{src}/{dst}",
            ttl=300
        )

    def station_board(self, station_code: str):
        code = self._normalize_station_code_for_api(station_code)
        return self._request(
            f"/stations/{code}/trains",
            ttl=60
        )

    def train_route(self, train_number: str):

        return self._request(
            f"/trains/{train_number}/route",
            ttl=86400
        )

    def train_lookup(self):

        return self._request(
            "/lookup/trains",
            ttl=86400
        )


_client_instance: RailRadarClient | None = None
_client_checked = False


def get_railradar_client() -> RailRadarClient | None:
    """Return a lazy singleton RailRadar client, or None if no API key is set."""
    global _client_instance, _client_checked

    if _client_checked:
        return _client_instance

    _client_checked = True

    if not API_KEY:
        logger.info("RAILRADAR_API_KEY not set — RailRadar client disabled.")
        return None

    try:
        _client_instance = RailRadarClient()
    except ValueError as exc:
        logger.warning("RailRadar client unavailable: %s", exc)
        _client_instance = None

    return _client_instance