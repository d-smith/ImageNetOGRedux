"""Route handlers for image endpoints.

These handlers are thin (per the service-layer separation standard): they parse
and validate request input, then delegate to ``services.images``. All business
logic and AWS access live in the service layer.

Routes:
    GET /v1/collections/{collection_name}/images
        → list_images
    GET /v1/collections/{collection_name}/images/{image_key}
        → get_image
"""

from typing import Any

from api_handler.app import app
from api_handler.params import (
    parse_date_range,
    parse_pagination,
    parse_sort,
    validate_collection_name,
    validate_image_key,
)
from api_handler.services import images as images_service

# Sort fields permitted for the images list endpoint.
_IMAGE_SORT_FIELDS = ["dateAdded"]


@app.get("/v1/collections/<collection_name>/images")  # type: ignore[misc]
def list_images(collection_name: str) -> dict[str, Any]:
    """Handle ``GET /v1/collections/{collection_name}/images``.

    Validates the collection-name path parameter and all query parameters
    before any AWS call, then returns a paginated envelope of public image
    records. Supports date-range listing, description-based vector search, or a
    combination of both.

    Args:
        collection_name: The collection name from the request path.

    Returns:
        A paginated images envelope (``{"items", "total", "limit", "offset"}``).

    Raises:
        InvalidParameterError: If the collection name or any query parameter is
            malformed.
        CollectionNotFoundError: If the collection does not exist.
    """
    event: dict[str, Any] = app.current_event.raw_event

    # 1. Validate path and query parameters before any AWS call.
    validate_collection_name(collection_name)
    pagination = parse_pagination(event)
    # ``sort``/``order`` are validated for correctness; ordering itself is
    # handled by the service (date sort) or the vector store (relevance rank).
    parse_sort(event, _IMAGE_SORT_FIELDS)
    date_range = parse_date_range(event, "addedAfter", "addedBefore")
    description = _query_value(event, "description")

    # 2. Delegate to the service layer.
    return dict(
        images_service.list_images(
            collection_name=collection_name,
            pagination=pagination,
            date_range=date_range,
            description=description,
        )
    )


@app.get("/v1/collections/<collection_name>/images/<image_key>")  # type: ignore[misc]
def get_image(collection_name: str, image_key: str) -> dict[str, Any]:
    """Handle ``GET /v1/collections/{collection_name}/images/{image_key}``.

    Validates both path parameters, then returns a time-limited presigned URL
    for the image object. The collection and image are both confirmed to exist
    (via DynamoDB) before a URL is generated, and the bucket name always comes
    from the collection record — never from caller input.

    Args:
        collection_name: The collection name from the request path.
        image_key: The image key from the request path.

    Returns:
        A mapping ``{"key", "url"}`` with the presigned GET URL.

    Raises:
        InvalidParameterError: If the collection name or image key is malformed.
        CollectionNotFoundError: If the collection does not exist.
        ImageNotFoundError: If the image key does not exist in the collection.
    """
    validate_collection_name(collection_name)
    validate_image_key(image_key)
    return dict(images_service.get_presigned_url(collection_name, image_key))


def _query_value(event: dict[str, Any], key: str) -> str | None:
    """Return a single non-empty query-string value, or ``None``."""
    qs = event.get("queryStringParameters") or {}
    if not isinstance(qs, dict):
        return None
    raw = qs.get(key)
    if raw is None or raw == "":
        return None
    return str(raw)
