from datetime import datetime, timedelta

from services.query_normalizer import normalize_date, normalize_time, normalize_params


def _next_weekday(start: datetime, weekday: int) -> str:
    days_ahead = (weekday - start.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (start + timedelta(days=days_ahead)).strftime("%d-%m-%Y")


def test_normalize_date_supports_relative_and_next_weekday():
    today = datetime.today()

    assert normalize_date("today") == today.strftime("%d-%m-%Y")
    assert normalize_date("tomorrow") == (today + timedelta(days=1)).strftime("%d-%m-%Y")
    assert normalize_date("day after tomorrow") == (today + timedelta(days=2)).strftime("%d-%m-%Y")
    assert normalize_date("next friday") == _next_weekday(today, 4)
    assert normalize_date("next monday") == _next_weekday(today, 0)


def test_normalize_time_supports_common_forms():
    assert normalize_time("5 pm") == "17:00"
    assert normalize_time("5:30 PM") == "17:30"
    assert normalize_time("evening") == "17:00"


def test_normalize_params_maps_aliases_and_structured_fields():
    params = normalize_params({
        "travel_date": "tomorrow",
        "after_time": "5 pm",
        "before_time": "8 pm",
        "train_type": "Vande Bharat",
        "sort_by": "Departure",
    })

    assert params["date"] == (datetime.today() + timedelta(days=1)).strftime("%d-%m-%Y")
    assert params["departure_after"] == "17:00"
    assert params["departure_before"] == "20:00"
    assert params["train_type"] == "Vande Bharat"
    assert params["sort_by"] == "departure"


def test_normalize_params_coerces_numeric_train_numbers_to_strings():
    params = normalize_params({"train_no": 20902})

    assert params["train_no"] == "20902"
