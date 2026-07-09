"""
NTES Client Wrapper

Provides a thin abstraction over the `ntes-client` package so the rest
of the application never depends directly on the library.

Future providers (RailYatri, RapidAPI, etc.) can be swapped in here
without changing the PRS agent.
"""

from __future__ import annotations

from typing import Any

from ntes import NTESClient
from ntes.exceptions import NTESError


class RailNTESClient:
    """
    Wrapper around the unofficial NTES client.
    """

    def __init__(self, timeout: int = 10, retries: int = 2):
        self.client = NTESClient(
            timeout=timeout,
            retries=retries,
        )

    def get_pnr_status(self, pnr: str) -> dict[str, Any]:
        """
        Fetch live PNR status from NTES.

        Returns
        -------
        dict
            Raw JSON returned by NTES.

        Raises
        ------
        RuntimeError
            If NTES cannot be reached or returns an unexpected error.
        """

        try:
            response = self.client.pnr_status(pnr)

            if not isinstance(response, dict):
                raise RuntimeError("Invalid response received from NTES.")

            return response

        except NTESError as e:
            raise RuntimeError(f"NTES error: {e}") from e

        except Exception as e:
            raise RuntimeError(f"Unable to fetch PNR status: {e}") from e


# -------------------------------------------------------------------
# Singleton instance
# -------------------------------------------------------------------

_ntes_client: RailNTESClient | None = None


def get_ntes_client() -> RailNTESClient:
    """
    Returns a singleton NTES client.
    """

    global _ntes_client

    if _ntes_client is None:
        _ntes_client = RailNTESClient()

    return _ntes_client