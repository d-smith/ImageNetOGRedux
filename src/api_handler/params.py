"""Query parameter parsing and validation for the api_handler Lambda.

This module is the single validation gate for all query parameters.  No
service function or route handler may call a boto3 client with input that has
not passed through the functions here first.

Validation order in every route handler:
1. Call ``parse_pagination`` → raises ``InvalidParameterError`` on bad input
2. Call ``parse_sort`` → raises ``InvalidParameterError`` for unknown fields
3. Call ``parse_date_range`` (if applicable) → raises on bad or inverted range
4. Only then call service functions that touch AWS

All functions accept the raw API Gateway proxy event dict and extract
``queryStringParameters`` themselves, defaulting missing keys safely.
"""

import re
from dataclasses import dataclass
from datetime import date

from api_handler.exceptions import InvalidParameterError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_LIMIT: int = 20
_DEFAULT_OFFSET: int = 0
_MIN_LIMIT: int = 1
_MAX_LIMIT: int = 100

# Collection names: lowercase alphanumeric + hyphens, 3–48 chars, must start
# and end with an alphanumeric character. Mirrors the pattern enforced by the
# admin collection script and the security-patterns steering.
_COLLECTION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")

# Image keys (S3 object keys) must not exceed this length or contain path
# traversal sequences (see security-patterns steering).
_MAX_IMAGE_KEY_LENGTH: int = 1024


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaginationParams:
    """Validated pagination parameters extracted from a request event.

    Attributes:
        limit: Maximum number of items to return (1–100).
        offset: Zero-based index of the first item to return.
    """

    limit: int
    offset: int


@dataclass(frozen=True)
class DateRangeParams:
    """Validated date range parameters extracted from a request event.

    Either or both fields may be ``None`` when not supplied by the caller.

    Attributes:
        after: Lower bound (inclusive).  ``None`` if not supplied.
        before: Upper bound (inclusive).  ``None`` if not supplied.
    """

    after: date | None
    before: date | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_qs(event: dict[str, object], key: str) -> str | None:
    """Extract a single query string value from an API Gateway proxy event.

    Args:
        event: The raw Lambda event dict.
        key: The query parameter name to look up.

    Returns:
        The string value if present and non-empty, otherwise ``None``.
    """
    qs: object = event.get("queryStringParameters") or {}
    if not isinstance(qs, dict):
        return None
    raw = qs.get(key)
    if raw is None or raw == "":
        return None
    return str(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pagination(event: dict[str, object]) -> PaginationParams:
    """Parse and validate ``limit`` and ``offset`` query parameters.

    Defaults: ``limit=20``, ``offset=0``.

    Args:
        event: The raw API Gateway proxy event dict.

    Returns:
        A :class:`PaginationParams` with validated ``limit`` and ``offset``.

    Raises:
        InvalidParameterError: If ``limit`` or ``offset`` is not a valid
            integer, if ``limit`` is outside [1, 100], or if ``offset`` is
            negative.
    """
    raw_limit = _get_qs(event, "limit")
    raw_offset = _get_qs(event, "offset")

    # --- limit ---
    if raw_limit is None:
        limit = _DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise InvalidParameterError("limit", "must be an integer") from None
        if limit < _MIN_LIMIT or limit > _MAX_LIMIT:
            raise InvalidParameterError(
                "limit",
                f"must be between {_MIN_LIMIT} and {_MAX_LIMIT}",
            )

    # --- offset ---
    if raw_offset is None:
        offset = _DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise InvalidParameterError("offset", "must be an integer") from None
        if offset < 0:
            raise InvalidParameterError("offset", "must be 0 or greater")

    return PaginationParams(limit=limit, offset=offset)


def parse_sort(
    event: dict[str, object],
    allowed_fields: list[str],
) -> tuple[str, str]:
    """Parse and validate ``sort`` and ``order`` query parameters.

    Defaults: ``sort=`` first element of ``allowed_fields``, ``order="asc"``.

    Args:
        event: The raw API Gateway proxy event dict.
        allowed_fields: Non-empty list of permitted sort field names.

    Returns:
        A ``(sort_field, order)`` tuple where ``order`` is ``"asc"`` or
        ``"desc"``.

    Raises:
        InvalidParameterError: If ``sort`` is not in ``allowed_fields``, or
            if ``order`` is not ``"asc"`` or ``"desc"``.
    """
    raw_sort = _get_qs(event, "sort")
    raw_order = _get_qs(event, "order")

    sort_field = raw_sort if raw_sort is not None else allowed_fields[0]
    if sort_field not in allowed_fields:
        raise InvalidParameterError(
            "sort",
            f"must be one of: {', '.join(allowed_fields)}",
        )

    order = raw_order if raw_order is not None else "asc"
    if order not in ("asc", "desc"):
        raise InvalidParameterError("order", "must be 'asc' or 'desc'")

    return sort_field, order


def parse_date(value: str, param_name: str) -> date:
    """Parse an ISO 8601 date string (YYYY-MM-DD).

    Args:
        value: The raw string value from the query parameter.
        param_name: The query parameter name, used in the error message.

    Returns:
        A :class:`datetime.date` object.

    Raises:
        InvalidParameterError: If ``value`` is not a valid ISO 8601 date.
    """
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidParameterError(
            param_name,
            f"must be a valid ISO 8601 date (YYYY-MM-DD), got {value!r}",
        ) from None


def parse_date_range(
    event: dict[str, object],
    after_param: str = "createdAfter",
    before_param: str = "createdBefore",
) -> DateRangeParams:
    """Parse and validate a pair of optional date-range query parameters.

    Both parameters are optional.  When both are supplied, ``after`` must
    be ≤ ``before``; an inverted range raises ``InvalidParameterError``.

    Args:
        event: The raw API Gateway proxy event dict.
        after_param: Query parameter name for the lower bound (default
            ``"createdAfter"``).
        before_param: Query parameter name for the upper bound (default
            ``"createdBefore"``).

    Returns:
        A :class:`DateRangeParams` with ``after`` and/or ``before`` set to
        :class:`datetime.date` values, or ``None`` when not supplied.

    Raises:
        InvalidParameterError: If either date string is malformed, or if
            ``after`` > ``before`` (inverted range).
    """
    raw_after = _get_qs(event, after_param)
    raw_before = _get_qs(event, before_param)

    after: date | None = parse_date(raw_after, after_param) if raw_after is not None else None
    before: date | None = parse_date(raw_before, before_param) if raw_before is not None else None

    if after is not None and before is not None and after > before:
        raise InvalidParameterError(
            before_param,
            f"{before_param} ({before}) must not be earlier than {after_param} ({after})",
        )

    return DateRangeParams(after=after, before=before)


def validate_collection_name(collection_name: str) -> None:
    """Validate a collection-name path parameter against the naming pattern.

    Collection names must be lowercase alphanumeric plus hyphens, 3–48
    characters, and must begin and end with an alphanumeric character. This
    guard runs before the value is used in any DynamoDB key or S3 bucket name
    (per the security-patterns steering).

    Args:
        collection_name: The raw collection name from the request path.

    Raises:
        InvalidParameterError: If ``collection_name`` does not match the
            required pattern.
    """
    if not _COLLECTION_NAME_RE.match(collection_name):
        raise InvalidParameterError(
            "collection_name",
            "must be 3–48 lowercase alphanumeric characters or hyphens, "
            "starting and ending with an alphanumeric character",
        )


def validate_image_key(image_key: str) -> None:
    """Validate an image-key path parameter before it touches any AWS call.

    Rejects path-traversal sequences and over-long keys (per the
    security-patterns steering). A presigned URL must never be generated for a
    key that could escape its intended prefix or that exceeds the S3 object-key
    length limit.

    Args:
        image_key: The raw image key from the request path.

    Raises:
        InvalidParameterError: If ``image_key`` contains a ``..`` path
            traversal sequence, or if it exceeds
            ``_MAX_IMAGE_KEY_LENGTH`` characters.
    """
    if ".." in image_key:
        raise InvalidParameterError("image_key", "Path traversal sequences are not permitted")
    if len(image_key) > _MAX_IMAGE_KEY_LENGTH:
        raise InvalidParameterError(
            "image_key",
            f"Key exceeds maximum length of {_MAX_IMAGE_KEY_LENGTH} characters",
        )
