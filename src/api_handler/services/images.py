"""Business logic for image resources.

The route handlers in ``routes/images.py`` are thin: they parse and validate
input, then call the functions here. All DynamoDB, Bedrock, S3 Vectors, and S3
access — and all public-shape transformation — happen in this module.

Search paths for :func:`list_images`:
* **Date-only** — no ``description`` supplied. Queries the ``date_added_epoch``
  LSI on the images table with a ``KeyConditionExpression`` (plus optional
  date-range bound) and paginates in-Lambda.
* **Description-only** — ``description`` supplied, no date range. Embeds the
  description via Bedrock Titan, queries S3 Vectors for the nearest ``limit``
  vectors, then hydrates metadata via ``batch_get_item``. Offset is ignored for
  vector search (S3 Vectors returns a ranked top-K).
* **Combined** — ``description`` plus a date range. Same as description-only,
  but a ``date_added_epoch`` ``$gte``/``$lte`` filter is pushed into
  ``query_vectors`` so the vector store performs the date filtering.

Security notes (see security-patterns steering):
* ``s3_bucket`` and ``s3vector_bucket`` are internal fields and are stripped
  from every response by :func:`to_public_image` before it leaves this layer.
* The ``description`` search string is stripped and truncated to 500 characters
  before it is embedded (never interpolated into a key or expression).
* The presigned-URL bucket name always comes from the confirmed DynamoDB
  collection record, never from caller input.
* boto3 clients are created once at module load, not per invocation.
"""

import json
from datetime import UTC, date, datetime
from typing import Any, TypedDict

import boto3
from boto3.dynamodb.conditions import ConditionBase, Key

from api_handler import config
from api_handler.exceptions import CollectionNotFoundError, ImageNotFoundError
from api_handler.params import DateRangeParams, PaginationParams

# Module-level clients (reused across warm invocations).
_dynamodb = boto3.resource("dynamodb")
_collections_table = _dynamodb.Table(config.COLLECTIONS_TABLE)
_images_table = _dynamodb.Table(config.IMAGES_TABLE)
_bedrock_runtime = boto3.client("bedrock-runtime")
_s3 = boto3.client("s3")

# The ``s3vectors`` client is created lazily (and cached) on first use rather
# than at module load. The botocore version pinned for this project does not
# register the ``s3vectors`` service model, so eagerly creating this client at
# import time would raise ``UnknownServiceError`` and break importing this
# module for the date-listing and presigned-URL paths that do not need it.
# Creating it lazily keeps the module importable while still reusing a single
# client across warm invocations (the standard warm-reuse benefit is preserved
# for every request that actually performs a vector search).
_s3vectors_client: Any = None


def _s3vectors() -> Any:
    """Return the cached ``s3vectors`` boto3 client, creating it on first use.

    Returns:
        The module-cached ``s3vectors`` boto3 client.
    """
    global _s3vectors_client
    if _s3vectors_client is None:
        _s3vectors_client = boto3.client("s3vectors")
    return _s3vectors_client


# Internal storage fields that must never appear in an API response.
INTERNAL_FIELDS = frozenset({"s3_bucket", "s3vector_bucket"})

# Name of the (single) S3 Vectors index inside each collection's vector bucket.
_VECTOR_INDEX_NAME = "images"

# LSI on the images table used for date-range queries within a collection.
_DATE_ADDED_INDEX = "date_added_epoch-index"

# Maximum length of a description search string before embedding.
_MAX_DESCRIPTION_LENGTH = 500


class PublicImage(TypedDict):
    """An image as returned to API consumers (no internal fields)."""

    key: str
    dateAdded: str  # noqa: N815 — public API field name is camelCase by contract
    description: str | None


class ImageListResponse(TypedDict):
    """Paginated envelope for the images list endpoint."""

    items: list[PublicImage]
    total: int
    limit: int
    offset: int


def to_public_image(item: dict[str, Any]) -> PublicImage:
    """Project a raw DynamoDB image item to its public shape.

    Args:
        item: A raw DynamoDB item dict for an image.

    Returns:
        A :class:`PublicImage` containing only ``key``, ``dateAdded``, and
        ``description`` (which may be ``None``). Internal storage fields
        (``s3_bucket``, ``s3vector_bucket``) are never included.
    """
    description = item.get("description")
    return {
        "key": item["image_key"],
        "dateAdded": item["date_added"],
        "description": description if description is not None else None,
    }


def list_images(
    collection_name: str,
    pagination: PaginationParams,
    date_range: DateRangeParams,
    description: str | None,
) -> ImageListResponse:
    """List images in a collection with date filtering and/or vector search.

    Validates the collection exists, then dispatches to one of three search
    paths depending on whether ``description`` and/or a date range is supplied.

    Args:
        collection_name: The validated collection name (path parameter).
        pagination: Validated limit/offset.
        date_range: Validated ``dateAdded`` bounds (either may be ``None``).
        description: Free-text vector-search query, or ``None`` for a plain
            date/listing query.

    Returns:
        An :class:`ImageListResponse` envelope.

    Raises:
        CollectionNotFoundError: If the collection does not exist.
    """
    # Confirm the collection exists before any query touches the images table.
    if not _collection_exists(collection_name):
        raise CollectionNotFoundError(collection_name)

    if description is None:
        return _list_by_date(collection_name, pagination, date_range)
    return _search_by_description(collection_name, pagination, date_range, description)


def get_presigned_url(collection_name: str, image_key: str) -> dict[str, str]:
    """Generate a time-limited presigned GET URL for an image object.

    Follows the presigned-URL security rules exactly: the collection record is
    fetched first (to obtain the trusted ``s3_bucket`` name), the image record
    is confirmed to exist, and only then is a URL generated using the bucket
    name from DynamoDB — never a name constructed from caller input.

    Args:
        collection_name: The validated collection name (path parameter).
        image_key: The validated image key (path parameter).

    Returns:
        A mapping ``{"key": image_key, "url": presigned_url}``. The internal
        bucket name is never included in the response.

    Raises:
        CollectionNotFoundError: If the collection does not exist.
        ImageNotFoundError: If the image key does not exist in the collection.
    """
    collection = _get_collection_record(collection_name)
    s3_bucket = str(collection["s3_bucket"])

    if not _image_exists(collection_name, image_key):
        raise ImageNotFoundError(collection_name, image_key)

    url: str = _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": s3_bucket, "Key": image_key},
        ExpiresIn=config.PRESIGNED_URL_TTL_SECONDS,
    )
    return {"key": image_key, "url": url}


# ---------------------------------------------------------------------------
# Date-only path
# ---------------------------------------------------------------------------


def _list_by_date(
    collection_name: str,
    pagination: PaginationParams,
    date_range: DateRangeParams,
) -> ImageListResponse:
    """List images by date using the ``date_added_epoch`` LSI.

    Queries the LSI with a ``KeyConditionExpression`` on ``collection_name``
    (plus an optional ``date_added_epoch`` range bound), then sorts by
    ``date_added_epoch`` and applies the offset/limit slice in-Lambda.

    Args:
        collection_name: The validated collection name.
        pagination: Validated limit/offset.
        date_range: Validated ``dateAdded`` bounds (either may be ``None``).

    Returns:
        An :class:`ImageListResponse` envelope.
    """
    key_condition: ConditionBase = Key("collection_name").eq(collection_name)

    after_epoch = _to_epoch(date_range.after) if date_range.after is not None else None
    before_epoch = _to_epoch(date_range.before) if date_range.before is not None else None
    if after_epoch is not None and before_epoch is not None:
        key_condition = key_condition & Key("date_added_epoch").between(after_epoch, before_epoch)
    elif after_epoch is not None:
        key_condition = key_condition & Key("date_added_epoch").gte(after_epoch)
    elif before_epoch is not None:
        key_condition = key_condition & Key("date_added_epoch").lte(before_epoch)

    items = _query_all(key_condition)
    items.sort(key=lambda i: i["date_added_epoch"])

    total = len(items)
    start = pagination.offset
    end = start + pagination.limit
    page = items[start:end]

    return {
        "items": [to_public_image(i) for i in page],
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
    }


def _query_all(key_condition: Any) -> list[dict[str, Any]]:
    """Query the images LSI, following pagination to collect all matches.

    Args:
        key_condition: A boto3 ``KeyConditionExpression``.

    Returns:
        The list of raw DynamoDB image items matching the condition.
    """
    items: list[dict[str, Any]] = []
    query_kwargs: dict[str, Any] = {
        "IndexName": _DATE_ADDED_INDEX,
        "KeyConditionExpression": key_condition,
    }
    while True:
        response = _images_table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if last_key is None:
            break
        query_kwargs["ExclusiveStartKey"] = last_key
    return items


# ---------------------------------------------------------------------------
# Description / combined vector-search path
# ---------------------------------------------------------------------------


def _search_by_description(
    collection_name: str,
    pagination: PaginationParams,
    date_range: DateRangeParams,
    description: str,
) -> ImageListResponse:
    """Vector-search images by description, optionally filtered by date.

    Embeds the (stripped, truncated) description, queries the collection's S3
    Vectors index for the nearest ``limit`` vectors — applying a
    ``date_added_epoch`` metadata filter when a date range is supplied — then
    hydrates the metadata for the returned keys via ``batch_get_item``.

    Note:
        ``offset`` is ignored for vector search; S3 Vectors returns a ranked
        top-K result set, so ``total`` equals the number of vectors returned.

    Args:
        collection_name: The validated collection name.
        pagination: Validated limit/offset (``limit`` maps to ``topK``).
        date_range: Validated ``dateAdded`` bounds (either may be ``None``).
        description: The free-text vector-search query.

    Returns:
        An :class:`ImageListResponse` envelope.
    """
    vector_bucket = str(_get_collection_record(collection_name)["s3vector_bucket"])

    embedding = _embed_description(description)

    query_kwargs: dict[str, Any] = {
        "vectorBucketName": vector_bucket,
        "indexName": _VECTOR_INDEX_NAME,
        "topK": pagination.limit,
        "queryVector": {"float32": embedding},
    }
    date_filter = _build_vector_date_filter(date_range)
    if date_filter is not None:
        query_kwargs["filter"] = date_filter

    # NOTE (test mocking): moto (pinned 5.1.22) does NOT implement
    # s3vectors:QueryVectors, so tests cannot exercise this call via @mock_aws.
    # The vector-search property tests stub the module-level ``_s3vectors``
    # client's ``query_vectors`` instead (see tests/property/test_image_properties.py,
    # Properties 13 & 14).
    response = _s3vectors().query_vectors(**query_kwargs)
    vectors = response.get("vectors", [])
    keys = [str(v["key"]) for v in vectors]

    items_by_key = _batch_get_images(collection_name, keys)
    # Preserve the ranked order returned by S3 Vectors.
    ordered = [items_by_key[k] for k in keys if k in items_by_key]

    return {
        "items": [to_public_image(i) for i in ordered],
        "total": len(ordered),
        "limit": pagination.limit,
        "offset": pagination.offset,
    }


def _embed_description(description: str) -> list[float]:
    """Embed a description string via Bedrock Titan text embedding.

    The description is stripped and truncated to 500 characters before being
    sent to Bedrock (per the security-patterns steering).

    Args:
        description: The raw description search string.

    Returns:
        The embedding as a list of floats.
    """
    sanitised = description.strip()[:_MAX_DESCRIPTION_LENGTH]
    response = _bedrock_runtime.invoke_model(
        modelId=config.EMBED_MODEL_ID,
        body=json.dumps({"inputText": sanitised}),
    )
    payload = json.loads(response["body"].read())
    embedding: list[float] = payload["embedding"]
    return embedding


def _build_vector_date_filter(date_range: DateRangeParams) -> dict[str, Any] | None:
    """Build an S3 Vectors metadata filter for the ``date_added_epoch`` range.

    Args:
        date_range: Validated ``dateAdded`` bounds.

    Returns:
        A ``{"date_added_epoch": {"$gte": ..., "$lte": ...}}`` filter mapping,
        or ``None`` if no bounds were supplied.
    """
    bounds: dict[str, int] = {}
    if date_range.after is not None:
        bounds["$gte"] = _to_epoch(date_range.after)
    if date_range.before is not None:
        bounds["$lte"] = _to_epoch(date_range.before)
    if not bounds:
        return None
    return {"date_added_epoch": bounds}


def _batch_get_images(collection_name: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    """Hydrate image metadata for a list of image keys via ``batch_get_item``.

    Args:
        collection_name: The parent collection name.
        keys: The image keys returned by the vector search.

    Returns:
        A mapping of ``image_key`` → raw DynamoDB image item. Keys with no
        matching record are omitted.
    """
    if not keys:
        return {}

    request_keys = [{"collection_name": collection_name, "image_key": k} for k in keys]
    items_by_key: dict[str, dict[str, Any]] = {}

    # batch_get_item accepts at most 100 keys per request.
    for start in range(0, len(request_keys), 100):
        chunk = request_keys[start : start + 100]
        request: dict[str, Any] = {config.IMAGES_TABLE: {"Keys": chunk}}
        while request:
            response = _dynamodb.batch_get_item(RequestItems=request)
            for item in response.get("Responses", {}).get(config.IMAGES_TABLE, []):
                items_by_key[str(item["image_key"])] = item
            request = response.get("UnprocessedKeys") or {}

    return items_by_key


# ---------------------------------------------------------------------------
# Collection / image record helpers
# ---------------------------------------------------------------------------


def _get_collection_record(collection_name: str) -> dict[str, Any]:
    """Fetch the raw collection record (including internal bucket fields).

    Unlike ``collections.get_collection``, this returns the raw item so the
    service can read the trusted ``s3_bucket`` / ``s3vector_bucket`` names. The
    raw item must never be returned to the response layer directly.

    Args:
        collection_name: The validated collection name.

    Returns:
        The raw DynamoDB collection item.

    Raises:
        CollectionNotFoundError: If the collection does not exist.
    """
    response = _collections_table.get_item(Key={"collection_name": collection_name})
    item = response.get("Item")
    if item is None:
        raise CollectionNotFoundError(collection_name)
    return item


def _collection_exists(collection_name: str) -> bool:
    """Return ``True`` if a collection record exists.

    Args:
        collection_name: The validated collection name.

    Returns:
        ``True`` if the collection exists, ``False`` otherwise.
    """
    response = _collections_table.get_item(Key={"collection_name": collection_name})
    return response.get("Item") is not None


def _image_exists(collection_name: str, image_key: str) -> bool:
    """Return ``True`` if an image record exists in the collection.

    Args:
        collection_name: The parent collection name.
        image_key: The image key to look up.

    Returns:
        ``True`` if the image exists, ``False`` otherwise.
    """
    response = _images_table.get_item(
        Key={"collection_name": collection_name, "image_key": image_key}
    )
    return response.get("Item") is not None


def _to_epoch(value: date) -> int:
    """Convert a date to a Unix timestamp (seconds) at UTC midnight."""
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
