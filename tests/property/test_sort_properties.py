"""Property tests for sort-field validation (task 23.2).

Property 7: for any string that is not a valid sort field for the requested
resource, supplying it as the ``sort`` query parameter causes the API to reject
the request with a 400 (``InvalidParameterError``).

The allowed sort fields differ per resource:
* Collections: ``name`` or ``created``
* Images: ``dateAdded``

``parse_sort`` is the single validation gate both route handlers call, so this
module exercises it directly against both resources' allowed-field sets. This
is broader than the sort arm in ``test_pagination_properties.py`` (which uses a
sampled pair of field sets); here we assert the accept/reject behaviour for the
exact collections and images field sets the endpoints use.

_Requirements: 5.7, 3.1, 3.2_
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from api_handler.exceptions import InvalidParameterError
from api_handler.params import parse_sort

# The exact allowed sort fields per endpoint (must match the route handlers).
_COLLECTION_SORT_FIELDS = ["name", "created"]
_IMAGE_SORT_FIELDS = ["dateAdded"]

_ALL_VALID = set(_COLLECTION_SORT_FIELDS) | set(_IMAGE_SORT_FIELDS)


def _event(**qs: str) -> dict[str, object]:
    return {"queryStringParameters": dict(qs)}


@given(
    fields=st.sampled_from([_COLLECTION_SORT_FIELDS, _IMAGE_SORT_FIELDS]),
    sort_value=st.text(max_size=40),
)
def test_invalid_sort_field_rejected(fields: list[str], sort_value: str) -> None:
    # Feature: aws-deployment-feature, Property 7: Sort field validation
    assume(sort_value not in fields)
    assume(sort_value != "")  # empty falls back to the default field
    with pytest.raises(InvalidParameterError) as exc:
        parse_sort(_event(sort=sort_value), fields)
    assert exc.value.param_name == "sort"


@given(sort_value=st.text(min_size=1, max_size=40))
def test_cross_resource_field_rejected_for_collections(sort_value: str) -> None:
    # Feature: aws-deployment-feature, Property 7: Sort field validation
    # A field valid for images ("dateAdded") is NOT valid for collections.
    assume(sort_value not in _COLLECTION_SORT_FIELDS)
    with pytest.raises(InvalidParameterError) as exc:
        parse_sort(_event(sort=sort_value), _COLLECTION_SORT_FIELDS)
    assert exc.value.param_name == "sort"


@given(sort_value=st.text(min_size=1, max_size=40))
def test_cross_resource_field_rejected_for_images(sort_value: str) -> None:
    # Feature: aws-deployment-feature, Property 7: Sort field validation
    # Fields valid for collections ("name"/"created") are NOT valid for images.
    assume(sort_value not in _IMAGE_SORT_FIELDS)
    with pytest.raises(InvalidParameterError) as exc:
        parse_sort(_event(sort=sort_value), _IMAGE_SORT_FIELDS)
    assert exc.value.param_name == "sort"


def test_dateadded_rejected_for_collections() -> None:
    # Concrete cross-resource case: images' only field is invalid for collections.
    with pytest.raises(InvalidParameterError):
        parse_sort(_event(sort="dateAdded"), _COLLECTION_SORT_FIELDS)


@pytest.mark.parametrize("field", _COLLECTION_SORT_FIELDS)
def test_collection_valid_fields_accepted(field: str) -> None:
    chosen, order = parse_sort(_event(sort=field), _COLLECTION_SORT_FIELDS)
    assert chosen == field
    assert order == "asc"


@pytest.mark.parametrize("field", _IMAGE_SORT_FIELDS)
def test_image_valid_fields_accepted(field: str) -> None:
    chosen, order = parse_sort(_event(sort=field), _IMAGE_SORT_FIELDS)
    assert chosen == field
    assert order == "asc"
