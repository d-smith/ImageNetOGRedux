"""Integration test (task 25.1): API Gateway authorization.

Verifies that the deployed API Gateway rejects requests without a valid JWT and
returns the project's structured JSON error contract. This exercises the
AWS-managed Cognito authorizer end-to-end (the behaviour that cannot be unit
tested — see task 23.1).

Run with a deployed stack:

    IMAGENETOG_API_BASE_URL=... AWS_PROFILE=terraform \\
        pytest -m integration tests/integration/test_auth_integration.py

_Requirements: 3.2_
"""

import pytest
import requests

pytestmark = pytest.mark.integration

_TIMEOUT = 15


def _assert_structured_401(response: requests.Response) -> None:
    """Assert a 401 with a JSON body carrying an error token + message."""
    assert (
        response.status_code == 401
    ), f"expected 401, got {response.status_code}: {response.text[:200]}"
    assert response.headers.get("Content-Type", "").startswith("application/json")
    body = response.json()
    assert "error" in body and isinstance(body["error"], str) and body["error"]
    assert "message" in body and isinstance(body["message"], str) and body["message"]


def test_missing_authorization_header_returns_401(api_base_url: str) -> None:
    response = requests.get(f"{api_base_url}/collections", timeout=_TIMEOUT)
    _assert_structured_401(response)


def test_invalid_bearer_token_returns_401(api_base_url: str) -> None:
    headers = {"Authorization": "Bearer not-a-real-token"}
    response = requests.get(f"{api_base_url}/collections", headers=headers, timeout=_TIMEOUT)
    _assert_structured_401(response)


def test_non_bearer_scheme_returns_401(api_base_url: str) -> None:
    headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    response = requests.get(f"{api_base_url}/collections", headers=headers, timeout=_TIMEOUT)
    _assert_structured_401(response)
