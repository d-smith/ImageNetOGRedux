"""Exception hierarchy for the api_handler Lambda.

All domain errors that map to a specific HTTP status code subclass ``APIError``.
Error tokens are defined here as class attributes and are the single source of
truth for all error token strings used in response bodies.

Usage::

    from api_handler.exceptions import CollectionNotFoundError, InvalidParameterError

    raise CollectionNotFoundError("nature-2024")
    raise InvalidParameterError("limit", "must be between 1 and 100")
"""


class APIError(Exception):
    """Base class for all API domain errors.

    Subclasses must declare ``http_status`` and ``error_token`` as class-level
    attributes.  The ``message`` attribute is set from the first positional
    argument (or via the ``message`` keyword argument) and is safe to include
    in response bodies — it must never contain internal resource names, ARNs,
    or tracebacks.

    Attributes:
        http_status: HTTP status code to return to the caller.
        error_token: Dot-separated error token string (e.g. ``"resource.not_found"``).
        message: Human-readable error message safe for API responses.
    """

    http_status: int = 500
    error_token: str = "server.error"  # noqa: S105 — not a credential

    def __init__(self, message: str = "An internal error occurred.") -> None:
        super().__init__(message)
        self.message: str = message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"http_status={self.http_status}, "
            f"error_token={self.error_token!r}, "
            f"message={self.message!r})"
        )


class CollectionNotFoundError(APIError):
    """Raised when a collection does not exist in the collections table.

    Args:
        collection_name: The collection name that was not found.
    """

    http_status = 404
    error_token = "resource.not_found"  # noqa: S105 — not a credential

    def __init__(self, collection_name: str) -> None:
        super().__init__(f"Collection '{collection_name}' not found.")
        self.collection_name = collection_name


class ImageNotFoundError(APIError):
    """Raised when an image key does not exist in the images table.

    Args:
        collection_name: The parent collection name.
        image_key: The image key that was not found.
    """

    http_status = 404
    error_token = "resource.not_found"  # noqa: S105 — not a credential

    def __init__(self, collection_name: str, image_key: str) -> None:
        super().__init__(f"Image '{image_key}' not found in collection '{collection_name}'.")
        self.collection_name = collection_name
        self.image_key = image_key


class InvalidParameterError(APIError):
    """Raised when a query or path parameter fails validation.

    Args:
        param_name: The name of the invalid parameter.
        reason: A human-readable explanation of why the value was rejected.
    """

    http_status = 400
    error_token = "param.invalid"  # noqa: S105 — not a credential

    def __init__(self, param_name: str, reason: str) -> None:
        super().__init__(f"Invalid parameter '{param_name}': {reason}")
        self.param_name = param_name
        self.reason = reason


class MethodNotAllowedError(APIError):
    """Raised when an HTTP method other than GET is used on a registered path.

    Args:
        method: The HTTP method that was attempted.
        path: The request path.
    """

    http_status = 405
    error_token = "method.not_allowed"  # noqa: S105 — not a credential

    def __init__(self, method: str, path: str) -> None:
        super().__init__(f"Method '{method}' is not allowed on '{path}'.")
        self.method = method
        self.path = path
