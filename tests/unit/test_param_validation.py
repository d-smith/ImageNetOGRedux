"""Unit tests for query parameter parsing/validation (task 9.2).

Covers boundary values (limit=1, 100, 101), invalid sort fields, invalid date
strings, and inverted date ranges.

_Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_
"""

from datetime import date

import pytest

from api_handler.exceptions import InvalidParameterError
from api_handler.params import (
    parse_date,
    parse_date_range,
    parse_pagination,
    parse_sort,
)

_COLLECTION_SORT_FIELDS = ["name", "created"]


def _event(**qs: str) -> dict[str, object]:
    """Build a proxy event with the given query string parameters."""
    return {"queryStringParameters": dict(qs) if qs else None}


class TestPagination:
    def test_defaults_when_absent(self) -> None:
        params = parse_pagination(_event())
        assert params.limit == 20
        assert params.offset == 0

    def test_limit_lower_boundary_accepted(self) -> None:
        assert parse_pagination(_event(limit="1")).limit == 1

    def test_limit_upper_boundary_accepted(self) -> None:
        assert parse_pagination(_event(limit="100")).limit == 100

    def test_limit_above_max_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_pagination(_event(limit="101"))
        assert exc.value.param_name == "limit"

    def test_limit_zero_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            parse_pagination(_event(limit="0"))

    def test_limit_non_integer_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_pagination(_event(limit="abc"))
        assert exc.value.param_name == "limit"

    def test_offset_negative_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_pagination(_event(offset="-1"))
        assert exc.value.param_name == "offset"

    def test_offset_non_integer_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            parse_pagination(_event(offset="1.5"))

    def test_offset_zero_accepted(self) -> None:
        assert parse_pagination(_event(offset="0")).offset == 0


class TestSort:
    def test_default_is_first_allowed_field(self) -> None:
        field, order = parse_sort(_event(), _COLLECTION_SORT_FIELDS)
        assert field == "name"
        assert order == "asc"

    def test_valid_field_accepted(self) -> None:
        field, _ = parse_sort(_event(sort="created"), _COLLECTION_SORT_FIELDS)
        assert field == "created"

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_sort(_event(sort="bogus"), _COLLECTION_SORT_FIELDS)
        assert exc.value.param_name == "sort"

    def test_desc_order_accepted(self) -> None:
        _, order = parse_sort(_event(order="desc"), _COLLECTION_SORT_FIELDS)
        assert order == "desc"

    def test_invalid_order_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_sort(_event(order="sideways"), _COLLECTION_SORT_FIELDS)
        assert exc.value.param_name == "order"


class TestParseDate:
    def test_valid_iso_date(self) -> None:
        assert parse_date("2024-01-15", "createdAfter") == date(2024, 1, 15)

    def test_invalid_date_string_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_date("not-a-date", "createdAfter")
        assert exc.value.param_name == "createdAfter"

    def test_non_iso_format_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            parse_date("01/15/2024", "createdAfter")

    def test_impossible_date_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            parse_date("2024-13-40", "createdAfter")


class TestDateRange:
    def test_both_absent_returns_none(self) -> None:
        result = parse_date_range(_event())
        assert result.after is None
        assert result.before is None

    def test_valid_range_parsed(self) -> None:
        result = parse_date_range(_event(createdAfter="2024-01-01", createdBefore="2024-12-31"))
        assert result.after == date(2024, 1, 1)
        assert result.before == date(2024, 12, 31)

    def test_equal_bounds_accepted(self) -> None:
        result = parse_date_range(_event(createdAfter="2024-06-01", createdBefore="2024-06-01"))
        assert result.after == result.before

    def test_inverted_range_rejected(self) -> None:
        with pytest.raises(InvalidParameterError) as exc:
            parse_date_range(_event(createdAfter="2024-12-31", createdBefore="2024-01-01"))
        assert exc.value.param_name == "createdBefore"

    def test_only_after_supplied(self) -> None:
        result = parse_date_range(_event(createdAfter="2024-01-01"))
        assert result.after == date(2024, 1, 1)
        assert result.before is None

    def test_malformed_bound_rejected(self) -> None:
        with pytest.raises(InvalidParameterError):
            parse_date_range(_event(createdAfter="garbage"))
