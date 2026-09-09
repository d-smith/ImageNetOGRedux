"""Route handlers for collection endpoints.

These handlers are thin (per the service-layer separation standard): they parse
and validate request input, then delegate to ``services.collections``. All
business logic and AWS access live in the service layer.

Routes:
    GET /v1/collections                   → list_collections
    GET /v1/collections/{collection_name} → get_collection
"""

from typing import Any

from api_handler.app import app
from api_handler.params import (
    parse_date_range,
    parse_pagination,
    parse_sort,
    validate_collection_name,
)
from api_handler.services import collections as collections_service

# Sort fields permitted for the collections list endpoint.
_COLLECTION_SORT_FIELDS = ["name", "created"]


@app.get("/v1/collections")  # type: ignore[misc]
def list_collections() -> dict[str, Any]:
    """Handle ``GET /v1/collections``.

    Parses and validates pagination, sort, ``name`` prefix, and ``createdAfter``
    / ``createdBefore`` date-range parameters, then returns a paginated envelope
    of public collection records.

    Returns:
        A paginated collections envelope
        (``{"items", "total", "limit", "offset"}``).
    """
    event: dict[str, Any] = app.current_event.raw_event

    # 1. Validate all query parameters before any AWS call.
    pagination = parse_pagination(event)
    sort_field, order = parse_sort(event, _COLLECTION_SORT_FIELDS)
    date_range = parse_date_range(event, "createdAfter", "createdBefore")
    name_prefix = _query_value(event, "name")

    # 2. Delegate to the service layer.
    return dict(
        collections_service.list_collections(
            pagination=pagination,
            sort_field=sort_field,
            order=order,
            date_range=date_range,
            name_prefix=name_prefix,
        )
    )


@app.get("/v1/collections/<collection_name>")  # type: ignore[misc]
def get_collection(collection_name: str) -> dict[str, Any]:
    """Handle ``GET /v1/collections/{collection_name}``.

    Validates the collection-name path parameter, then returns the public
    collection record.

    Args:
        collection_name: The collection name from the request path.

    Returns:
        The public collection record (``{"name", "created"}``).

    Raises:
        InvalidParameterError: If the collection name is malformed.
        CollectionNotFoundError: If the collection does not exist.
    """
    validate_collection_name(collection_name)
    return dict(collections_service.get_collection(collection_name))


def _query_value(event: dict[str, Any], key: str) -> str | None:
    """Return a single non-empty query-string value, or ``None``."""
    qs = event.get("queryStringParameters") or {}
    if not isinstance(qs, dict):
        return None
    raw = qs.get(key)
    if raw is None or raw == "":
        return None
    return str(raw)
