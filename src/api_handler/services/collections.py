"""Business logic for collection resources.

The route handlers in ``routes/collections.py`` are thin: they parse and
validate input, then call the functions here. All DynamoDB access and all
public-shape transformation happen in this module.

Security notes (see security-patterns steering):
* ``s3_bucket`` and ``s3vector_bucket`` are internal fields and are stripped
  from every response by :func:`to_public_collection` before it leaves this
  layer. Route handlers never see raw DynamoDB items.
* The boto3 resource is created once at module load, not per invocation.
"""

from datetime import UTC, date, datetime
from typing import Any, TypedDict

import boto3
from boto3.dynamodb.conditions import Attr, ConditionBase

from api_handler import config
from api_handler.exceptions import CollectionNotFoundError
from api_handler.params import DateRangeParams, PaginationParams

# Module-level client (reused across warm invocations).
_dynamodb = boto3.resource("dynamodb")
_collections_table = _dynamodb.Table(config.COLLECTIONS_TABLE)

# Internal storage fields that must never appear in an API response.
INTERNAL_FIELDS = frozenset({"s3_bucket", "s3vector_bucket"})

# Map of API sort field name → DynamoDB attribute used for ordering.
_SORT_ATTR = {"name": "collection_name", "created": "created_epoch"}


class PublicCollection(TypedDict):
    """A collection as returned to API consumers (no internal fields)."""

    name: str
    created: str


class CollectionListResponse(TypedDict):
    """Paginated envelope for the collections list endpoint."""

    items: list[PublicCollection]
    total: int
    limit: int
    offset: int


def to_public_collection(item: dict[str, Any]) -> PublicCollection:
    """Project a raw DynamoDB collection item to its public shape.

    Args:
        item: A raw DynamoDB item dict for a collection.

    Returns:
        A :class:`PublicCollection` containing only ``name`` and ``created``.
    """
    return {"name": item["collection_name"], "created": item["created"]}


def list_collections(
    pagination: PaginationParams,
    sort_field: str,
    order: str,
    date_range: DateRangeParams,
    name_prefix: str | None,
) -> CollectionListResponse:
    """List collections with filtering, sorting, and pagination.

    Scans the collections table, applies the ``name`` prefix filter
    (case-insensitive) and ``created`` date-range filter in-Lambda, sorts the
    result, then applies the offset/limit slice.

    Args:
        pagination: Validated limit/offset.
        sort_field: One of ``"name"`` or ``"created"``.
        order: ``"asc"`` or ``"desc"``.
        date_range: Validated ``created`` date bounds (either may be ``None``).
        name_prefix: Case-insensitive name prefix filter, or ``None``.

    Returns:
        A :class:`CollectionListResponse` envelope.
    """
    items = _scan_collections(date_range)

    if name_prefix:
        prefix_lower = name_prefix.lower()
        items = [i for i in items if str(i["collection_name"]).lower().startswith(prefix_lower)]

    reverse = order == "desc"
    sort_attr = _SORT_ATTR[sort_field]
    items.sort(key=lambda i: i[sort_attr], reverse=reverse)

    total = len(items)
    start = pagination.offset
    end = start + pagination.limit
    page = items[start:end]

    return {
        "items": [to_public_collection(i) for i in page],
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
    }


def get_collection(collection_name: str) -> PublicCollection:
    """Fetch a single collection by name.

    Args:
        collection_name: The validated collection name (path parameter).

    Returns:
        The :class:`PublicCollection` for ``collection_name``.

    Raises:
        CollectionNotFoundError: If no collection with that name exists.
    """
    response = _collections_table.get_item(Key={"collection_name": collection_name})
    item = response.get("Item")
    if item is None:
        raise CollectionNotFoundError(collection_name)
    return to_public_collection(item)


def _scan_collections(date_range: DateRangeParams) -> list[dict[str, Any]]:
    """Scan the collections table, applying the created_epoch range as a filter.

    The date range is pushed to DynamoDB as a ``FilterExpression`` where
    possible; the remaining (prefix, sort, slice) work happens in-Lambda.

    Args:
        date_range: Validated ``created`` date bounds.

    Returns:
        The list of raw DynamoDB items matching the date range.
    """
    filter_expr = _build_date_filter(date_range)
    scan_kwargs: dict[str, Any] = {}
    if filter_expr is not None:
        scan_kwargs["FilterExpression"] = filter_expr

    items: list[dict[str, Any]] = []
    while True:
        response = _collections_table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if last_key is None:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    return items


def _build_date_filter(date_range: DateRangeParams) -> ConditionBase | None:
    """Build a DynamoDB FilterExpression for the created_epoch range.

    Args:
        date_range: Validated ``created`` date bounds.

    Returns:
        A boto3 condition expression, or ``None`` if no bounds were supplied.
    """
    conditions: list[ConditionBase] = []
    if date_range.after is not None:
        conditions.append(Attr("created_epoch").gte(_to_epoch(date_range.after)))
    if date_range.before is not None:
        conditions.append(Attr("created_epoch").lte(_to_epoch(date_range.before)))

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return conditions[0] & conditions[1]


def _to_epoch(value: date) -> int:
    """Convert a date to a Unix timestamp (seconds) at UTC midnight."""
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
