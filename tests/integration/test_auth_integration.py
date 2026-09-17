"""Integration test (task 25.1): API Gateway authorization.

Verifies that the deployed API Gateway **rejects** requests that do not carry a
valid JWT. This exercises the AWS-managed Cognito authorizer end-to-end (the
behaviour that cannot be unit tested — see task 23.1).

Note on status codes: API Gateway is not uniform here. For a request that
carries no usable credentials at all (missing ``Authorization`` header, or a
header that is not a well-formed ``Bearer`` token), the gateway typically
returns **403** with its default ``Missing Authentication Token`` /
``Invalid ... Authorization header`` body — the request never reaches the
Cognito authorizer's token-validation path. A structurally valid but invalid
token reaches the authorizer and yields **401** via the ``UNAUTHORIZED``
gateway response with our structured JSON contract.

These tests therefore assert the security-relevant invariant — the request is
**rejected** (401 or 403), never served — and additionally assert the
structured JSON error contract whenever the response is a 401.

Run with a deployed stack:

    IMAGENETOG_API_BASE_URL=... AWS_PROFILE=terraform \\
        pytest -m integration tests/integration/test_auth_integration.py

_Requirements: 3.2_
"""

import pytest
import requests

pytestmark = pytest.mark.integration

_TIMEOUT = 15
_REJECTED = (401, 403)


def _assert_rejected(response: requests.Response) -> None:
    """Assert the request was rejected as unauthenticated (401 or 403).

    When the rejection is a 401 (the Cognito ``UNAUTHORIZED`` gateway-response
    path), also assert the project's structured JSON error contract
    (``{"error": "<token>", "message": "<msg>"}`` with a JSON content type).

    Critically, a 403 must NOT be an IAM/SigV4 rejection
    (``IncompleteSignatureException`` / "Authorization header requires
    'Credential'/'Signature'/'SignedHeaders'"). That specific error means the
    request was routed to API Gateway's IAM authorizer instead of the Cognito
    authorizer — the signature of a stage-name/``/v1``-path collision — and must
    be treated as a failure, not an acceptable rejection.
    """
    assert response.status_code in _REJECTED, (
        f"expected one of {_REJECTED} (unauthenticated request must be rejected), "
        f"got {response.status_code}: {response.text[:200]}"
    )

    # A Cognito-protected route never rejects via IAM/SigV4. If it does, the
    # route is misconfigured (e.g. stage name collides with the /v1 prefix).
    text = response.text
    assert "IncompleteSignatureException" not in text and "requires 'Signature'" not in text, (
        "unauthenticated request was rejected by the IAM/SigV4 authorizer, not "
        "the Cognito authorizer — the route is misconfigured (check the stage "
        f"name vs the /v1 path prefix). Body: {text[:300]}"
    )

    if response.status_code == 401:
        assert response.headers.get("Content-Type", "").startswith("application/json")
        body = response.json()
        assert "error" in body and isinstance(body["error"], str) and body["error"]
        assert "message" in body and isinstance(body["message"], str) and body["message"]


def test_missing_authorization_header_is_rejected(api_base_url: str) -> None:
    response = requests.get(f"{api_base_url}/collections", timeout=_TIMEOUT)
    _assert_rejected(response)


def test_invalid_bearer_token_is_rejected(api_base_url: str) -> None:
    headers = {"Authorization": "Bearer not-a-real-token"}
    response = requests.get(f"{api_base_url}/collections", headers=headers, timeout=_TIMEOUT)
    _assert_rejected(response)


def test_non_bearer_scheme_is_rejected(api_base_url: str) -> None:
    headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    response = requests.get(f"{api_base_url}/collections", headers=headers, timeout=_TIMEOUT)
    _assert_rejected(response)
