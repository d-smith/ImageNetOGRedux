"""Integration test (task 25.2): API Gateway rate-limiting configuration.

This test verifies the **structural properties** required for API Gateway to
enforce rate limiting, rather than attempting to trigger throttling with a live
request burst. The behavioural approach (burst until a 429) is timing- and
account-sensitive, requires a valid JWT (throttling is applied post-auth), and
is inherently flaky; asserting the configuration is deterministic and needs no
token or generated load.

It verifies, against the deployed environment:

1. A usage plan ``{env}-imagenetog-usage-plan`` exists.
2. The usage plan declares a throttle rate limit and burst limit (both > 0).
3. The usage plan is attached to the deployed REST API's stage — without this
   linkage the throttle settings are inert.
4. The API defines a ``THROTTLED`` gateway response returning the project's
   structured JSON error contract (so a throttled caller receives
   ``rate_limit.exceeded`` rather than API Gateway's default body).

These four together are exactly what makes the gateway enforce rate limiting
with the expected 429 error contract.

_Requirements: 9.1, 9.2_
"""

import json

import pytest
from botocore.exceptions import BotoCoreError, ClientError

pytestmark = pytest.mark.integration

# Errors that mean "no usable AWS access in this environment" — the suite
# contract is to SKIP (not fail) when the deployment/credentials are absent.
_NO_AWS_ERRORS = (BotoCoreError, ClientError)


def _find_rest_api(apigateway_client: object, env_name: str) -> dict:
    """Return the deployed REST API resource for the environment."""
    name = f"{env_name}-imagenetog-api"
    try:
        apis = apigateway_client.get_rest_apis(limit=500)["items"]  # type: ignore[attr-defined]
    except _NO_AWS_ERRORS as exc:
        pytest.skip(f"AWS API Gateway not reachable (no deployment/credentials?): {exc}")
    matches = [a for a in apis if a.get("name") == name]
    if not matches:
        pytest.skip(f"no deployed REST API named {name!r} found (is the env deployed?)")
    return matches[0]


def _find_usage_plan(apigateway_client: object, env_name: str) -> dict:
    """Return the deployed usage plan for the environment."""
    name = f"{env_name}-imagenetog-usage-plan"
    try:
        plans = apigateway_client.get_usage_plans(limit=500)["items"]  # type: ignore[attr-defined]
    except _NO_AWS_ERRORS as exc:
        pytest.skip(f"AWS API Gateway not reachable (no deployment/credentials?): {exc}")
    matches = [p for p in plans if p.get("name") == name]
    assert matches, f"usage plan {name!r} not found — rate limiting is not configured"
    return matches[0]


def test_usage_plan_has_throttle_settings(apigateway_client: object, env_name: str) -> None:
    plan = _find_usage_plan(apigateway_client, env_name)
    throttle = plan.get("throttle") or {}
    assert throttle.get("rateLimit", 0) > 0, f"usage plan has no positive rateLimit: {throttle}"
    assert throttle.get("burstLimit", 0) > 0, f"usage plan has no positive burstLimit: {throttle}"


def test_usage_plan_attached_to_api_stage(apigateway_client: object, env_name: str) -> None:
    api = _find_rest_api(apigateway_client, env_name)
    plan = _find_usage_plan(apigateway_client, env_name)

    api_stages = plan.get("apiStages") or []
    api_ids = {s.get("apiId") for s in api_stages}
    assert api["id"] in api_ids, (
        f"usage plan is not attached to REST API {api['id']!r}; throttle settings "
        f"are inert. Attached stages: {api_stages}"
    )


def test_throttled_gateway_response_returns_structured_json(
    apigateway_client: object, env_name: str
) -> None:
    api = _find_rest_api(apigateway_client, env_name)

    try:
        resp = apigateway_client.get_gateway_response(  # type: ignore[attr-defined]
            restApiId=api["id"], responseType="THROTTLED"
        )
    except _NO_AWS_ERRORS as exc:
        pytest.skip(f"AWS API Gateway not reachable (no deployment/credentials?): {exc}")

    # 429 status and a JSON template carrying the rate_limit.exceeded token.
    assert resp.get("statusCode") == "429"
    templates = resp.get("responseTemplates") or {}
    body = templates.get("application/json")
    assert body, f"THROTTLED gateway response has no application/json template: {resp}"
    parsed = json.loads(body)
    assert parsed.get("error") == "rate_limit.exceeded"
    assert parsed.get("message")
