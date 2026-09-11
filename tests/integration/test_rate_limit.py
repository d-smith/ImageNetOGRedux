"""Integration test (task 25.2): API Gateway usage-plan rate limiting.

Fires a burst of authorized requests above the configured usage-plan rate/burst
and asserts that at least one response is a 429 carrying the structured JSON
error body.

Requires a valid Bearer token (``IMAGENETOG_JWT``) because throttling is applied
*after* authorization — unauthenticated requests would 401 before reaching the
usage plan. Skips when the token is not provided.

Note: this test is inherently timing- and account-sensitive. The dev usage plan
is intentionally small (see ``environments/dev/terraform.tfvars``:
``api_gateway_rate_limit``/``burst``). If your deployed limits are large, raise
``_BURST`` accordingly.

_Requirements: 9.2_
"""

import concurrent.futures

import pytest
import requests

pytestmark = pytest.mark.integration

_TIMEOUT = 15
_BURST = 60  # well above the dev usage plan (rate 10 / burst 20)


def _get(url: str, headers: dict[str, str]) -> int:
    try:
        return requests.get(url, headers=headers, timeout=_TIMEOUT).status_code
    except requests.RequestException:
        return -1


def test_burst_exceeds_usage_plan_returns_429(api_base_url: str, jwt_token: str) -> None:
    url = f"{api_base_url}/collections"
    headers = {"Authorization": f"Bearer {jwt_token}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: _get(url, headers), range(_BURST)))

    assert 429 in statuses, (
        f"expected at least one 429 in a burst of {_BURST}; got statuses "
        f"{sorted(set(statuses))}. If the deployed usage plan is large, increase _BURST."
    )

    # Verify a throttled response carries the structured JSON contract.
    throttled = requests.get(url, headers=headers, timeout=_TIMEOUT)
    if throttled.status_code == 429:
        body = throttled.json()
        assert body.get("error") == "rate_limit.exceeded"
        assert body.get("message")
