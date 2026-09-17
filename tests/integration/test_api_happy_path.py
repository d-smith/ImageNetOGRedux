"""Integration test: authenticated happy path through the deployed API.

This is the counterpart to ``test_auth_integration.py`` (which only asserts that
*unauthenticated* requests are rejected). Here we mint a real Cognito ID token
and assert an authenticated request is actually **served** with the documented
response shape.

Why this matters: a rejection-only test suite cannot distinguish a working API
from a badly-misconfigured one. In particular, a stage-name/`/v1`-path collision
routes every request to API Gateway's default IAM authorizer and returns
``403 IncompleteSignatureException`` — which a "must be rejected (401/403)" test
happily accepts. A happy-path assertion (valid token -> 200 + JSON envelope) is
what catches that class of misconfiguration.

Requires ``IMAGENETOG_API_BASE_URL``, ``IMAGENETOG_APP_CLIENT_ID``,
``IMAGENETOG_TEST_USERNAME`` and ``IMAGENETOG_TEST_PASSWORD`` (and the app client
to allow ``USER_PASSWORD_AUTH`` — dev/staging). Skips cleanly otherwise.

_Requirements: 2.1, 3.1_
"""

import pytest
import requests

pytestmark = pytest.mark.integration

_TIMEOUT = 15


def test_authenticated_list_collections_succeeds(api_base_url: str, id_token: str) -> None:
    """A valid ID token in the raw Authorization header returns 200 + envelope."""
    response = requests.get(
        f"{api_base_url}/collections",
        headers={"Authorization": id_token},
        timeout=_TIMEOUT,
    )

    # The security-relevant, misconfiguration-catching assertion: an
    # authenticated request must be SERVED (200), not rejected/misrouted.
    assert response.status_code == 200, (
        "authenticated GET /collections must return 200; "
        f"got {response.status_code}: {response.text[:300]}"
    )

    # Guard specifically against the SigV4/IAM misrouting signature.
    assert "IncompleteSignatureException" not in response.text, (
        "response indicates the request was routed to IAM/SigV4 auth instead of "
        "the Cognito authorizer — check the stage name does not collide with the "
        "/v1 path prefix."
    )

    assert response.headers.get("Content-Type", "").startswith("application/json")
    body = response.json()
    # Documented paginated envelope shape.
    for field in ("items", "total", "limit", "offset"):
        assert field in body, f"missing '{field}' in collections envelope: {body}"
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


def test_authenticated_request_reaches_lambda_not_iam(api_base_url: str, id_token: str) -> None:
    """Even if data is empty, a valid token must not yield a SigV4/IAM error."""
    response = requests.get(
        f"{api_base_url}/collections",
        headers={"Authorization": id_token},
        timeout=_TIMEOUT,
    )
    assert response.status_code != 403 or "IncompleteSignatureException" not in response.text, (
        f"valid token produced an IAM/SigV4 rejection ({response.status_code}); "
        "the Cognito authorizer is not being invoked for this route."
    )
