"""
PNR Service

Coordinates live PNR retrieval from NTES and converts the
response into the application's normalized format.
"""

from __future__ import annotations

from typing import Any

from services.ntes_client import get_ntes_client
from services.pnr_normalizer import normalize_pnr_response


def get_live_pnr_status(pnr: str) -> dict[str, Any]:
    """
    Fetch and normalize live PNR status.

    Parameters
    ----------
    pnr : str
        10-digit PNR number.

    Returns
    -------
    dict
        Standardized PNR response.
    """

    try:
        client = get_ntes_client()

        raw_response = client.get_pnr_status(pnr)

        normalized = normalize_pnr_response(raw_response)

        # Preserve the raw response for debugging if needed
        normalized["raw_ntes_response"] = raw_response

        trace = normalized.get("trace_step", "")

        if trace:
            normalized["trace_step"] = (
                trace
                + " -> [PRS Service] Live PNR fetched from NTES."
            )
        else:
            normalized["trace_step"] = (
                "[PRS Service] Live PNR fetched from NTES."
            )

        return normalized

    except Exception as e:

        return {
            "error": str(e),
            "trace_step": (
                f"[PRS Service] Failed to fetch live PNR: {e}"
            ),
        }