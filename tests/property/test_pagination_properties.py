"""Property tests for pagination and sort validation (task 9.3).

Scope note: Properties 4 (slice correctness) and 5 (metadata accuracy) describe
list-endpoint response behaviour and are validated against the collection/image
route handlers (tasks 12.2 / 14.2), which do not exist yet. This module covers
the properties that live entirely in the ``params.py`` validation gate:

* Property 6: ``limit > 100`` → 400 (``InvalidParameterError``); ``limit`` in
  ``[1, 100]`` → accepted.
* Property 7: any string that is not a valid sort field → 400.

_Requirements: 5.4, 5.7_
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from api_handler.exceptions import InvalidParameterError
from api_handler.params import parse_pagination, parse_sort

_COLLECTION_SORT_FIELDS = ["name", "created"]
_IMAGE_SORT_FIELDS = ["dateAdded"]


def _event(**qs: str) -> dict[str, object]:
    return {"queryStringParameters": dict(qs)}


@given(limit=st.integers(min_value=1, max_value=100))
def test_limit_in_bounds_accepted(limit: int) -> None:
    # Feature: aws-deployment-feature, Property 6: Limit bounds enforcement
    params = parse_pagination(_event(limit=str(limit)))
    assert params.limit == limit


@given(limit=st.integers(min_value=101, max_value=10_000))
def test_limit_above_max_rejected(limit: int) -> None:
    # Feature: aws-deployment-feature, Property 6: Limit bounds enforcement
    with pytest.raises(InvalidParameterError) as exc:
        parse_pagination(_event(limit=str(limit)))
    assert exc.value.param_name == "limit"


@given(limit=st.integers(max_value=0))
def test_limit_below_min_rejected(limit: int) -> None:
    # Feature: aws-deployment-feature, Property 6: Limit bounds enforcement
    with pytest.raises(InvalidParameterError) as exc:
        parse_pagination(_event(limit=str(limit)))
    assert exc.value.param_name == "limit"


@given(offset=st.integers(min_value=0, max_value=1_000_000))
def test_valid_offset_roundtrips(offset: int) -> None:
    # Feature: aws-deployment-feature, Property 6: Limit bounds enforcement (offset arm)
    params = parse_pagination(_event(offset=str(offset)))
    assert params.offset == offset


@given(
    fields=st.sampled_from([_COLLECTION_SORT_FIELDS, _IMAGE_SORT_FIELDS]),
    sort_value=st.text(min_size=0, max_size=30),
)
def test_invalid_sort_field_rejected(fields: list[str], sort_value: str) -> None:
    # Feature: aws-deployment-feature, Property 7: Sort field validation
    assume(sort_value not in fields)
    assume(sort_value != "")  # empty string falls back to the default field
    with pytest.raises(InvalidParameterError) as exc:
        parse_sort(_event(sort=sort_value), fields)
    assert exc.value.param_name == "sort"


@given(fields=st.sampled_from([_COLLECTION_SORT_FIELDS, _IMAGE_SORT_FIELDS]))
def test_every_valid_sort_field_accepted(fields: list[str]) -> None:
    # Feature: aws-deployment-feature, Property 7: Sort field validation (accept arm)
    for field in fields:
        chosen, _ = parse_sort(_event(sort=field), fields)
        assert chosen == field
