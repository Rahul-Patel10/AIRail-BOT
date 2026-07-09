"""
PNR Response Normalizer

Converts the raw NTES response into the standard structure used
throughout the application.

This isolates all provider-specific field names from the rest
of the codebase.
"""

from __future__ import annotations

from typing import Any


def normalize_pnr_response(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize raw NTES PNR response.

    Parameters
    ----------
    raw : dict
        Raw JSON returned by NTES.

    Returns
    -------
    dict
        Normalized response understood by the PRS agent.
    """

    # ----------------------------
    # Error Response
    # ----------------------------

    if raw.get("reasonType") == "E":
        return {
            "error": raw.get("errorMessage", "Unable to fetch PNR."),
            "trace_step": "[PRS] NTES returned an error.",
        }

    passenger_list = raw.get("passengerList", [])

    first_passenger = passenger_list[0] if passenger_list else {}

    normalized = {
        "pnr_data": {
            "pnr": raw.get("pnrNumber"),

            "train_no": raw.get("trainNumber"),
            "train_name": raw.get("trainName"),

            "from_code": raw.get("sourceStation"),
            "from_station": raw.get("sourceStation"),

            "to_code": raw.get("destinationStation"),
            "to_station": raw.get("destinationStation"),

            "boarding_point": raw.get("boardingPoint"),
            "reservation_upto": raw.get("reservationUpto"),

            "travel_date": raw.get("dateOfJourney"),
            "arrival_date": raw.get("arrivalDate"),

            "travel_class": raw.get("journeyClass"),

            "booking_status": first_passenger.get("bookingStatus"),
            "current_status": first_passenger.get("currentStatus"),

            "coach": first_passenger.get("currentCoachId")
            or first_passenger.get("bookingCoachId"),

            "seat_no": first_passenger.get("currentBerthNo")
            or first_passenger.get("bookingBerthNo"),

            "berth_type": first_passenger.get("currentBerthCode")
            or first_passenger.get("bookingBerthCode"),

            "booking_status_details": first_passenger.get(
                "bookingStatusDetails"
            ),

            "current_status_details": first_passenger.get(
                "currentStatusDetails"
            ),

            "quota": raw.get("quota"),

            "fare": raw.get("ticketFare"),

            "chart_status": raw.get("chartStatus"),

            "distance": raw.get("distance"),

            "ticket_type": raw.get("ticketTypeInPrs"),

            "vikalp_status": raw.get("vikalpStatus"),

            "booking_date": raw.get("bookingDate"),

            "passenger_count": raw.get("numberOfpassenger", 0),

            "passengers": passenger_list,

            "raw_response": raw,
        },

        "trace_step": "[PRS] Live PNR normalized successfully.",
    }

    return normalized