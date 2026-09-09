"""Property tests for router method/version enforcement (task 10.4).

* Property 1: any non-GET HTTP method on a registered ``/v1/`` path → 405.
* Property 2: any path that does not begin with ``/v1/`` → 404, before any
  handler runs.

_Requirements: 1.1, 1.2, 2.1, 2.2_
"""

import json

from hypothesis import given
from hypothesis import strategies as st

from api_handler import app as app_module

# Standard non-GET HTTP methods (GET is the only permitted method).
_NON_GET_METHODS = ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


def _register_stub_route() -> None:
    resolver = app_module.app
    existing = {r.path for r in resolver._static_routes + resolver._dynamic_routes}  # type: ignore[attr-defined]
    if "/v1/collections" in existing:
        return

    @resolver.get("/v1/collections")
    def _list_collections_stub() -> dict:  # pragma: no cover - routing target
        return {"items": []}


_register_stub_route()


def _event(method: str, path: str) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "queryStringParameters": None,
        "headers": {},
        "requestContext": {"httpMethod": method, "path": path},
    }


@given(method=st.sampled_from(_NON_GET_METHODS))
def test_non_get_on_registered_path_is_405(method: str) -> None:
    # Feature: aws-deployment-feature, Property 1: Read-only endpoint enforcement
    response = app_module.resolve(_event(method, "/v1/collections"), None)
    assert response["statusCode"] == 405
    assert json.loads(response["body"])["error"] == "method.not_allowed"


# Path segments that never start with "/v1/". We build arbitrary paths and
# filter out anything that happens to begin with the versioned prefix.
_path_segment = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789/-_",
    min_size=0,
    max_size=40,
)


@given(suffix=_path_segment)
def test_non_v1_path_is_404(suffix: str) -> None:
    # Feature: aws-deployment-feature, Property 2: API versioning enforcement
    path = "/" + suffix
    if path.startswith("/v1/"):
        path = "/x" + path  # force it out of the /v1/ namespace
    assert not path.startswith("/v1/")

    response = app_module.resolve(_event("GET", path), None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"] == "resource.not_found"


@given(
    method=st.sampled_from(_NON_GET_METHODS),
    suffix=_path_segment,
)
def test_non_v1_path_is_404_regardless_of_method(method: str, suffix: str) -> None:
    # Feature: aws-deployment-feature, Property 2: API versioning enforcement
    # The version guard runs before the method guard, so a non-/v1/ path is a
    # 404 even for a non-GET method.
    path = "/" + suffix
    if path.startswith("/v1/"):
        path = "/x" + path
    response = app_module.resolve(_event(method, path), None)
    assert response["statusCode"] == 404
