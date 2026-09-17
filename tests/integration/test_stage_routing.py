"""Integration test: API Gateway stage name must not collide with the /v1 path.

The API versions its resources under a ``/v1`` path prefix. If the deployment
**stage** is also named ``v1``, the invoke path ``/{stage}/v1/...`` would need to
be ``/v1/v1/...`` to match — and ``/v1/...`` falls through to API Gateway's
default IAM authorizer, producing a misleading ``403 IncompleteSignatureException``
for every request (this exact misconfiguration cost a lengthy debugging session).

This is a deterministic structural check (no token, no timing sensitivity): it
inspects the deployed stages and the resource tree and asserts the stage name is
distinct from any top-level path segment. Skips cleanly without AWS creds /
``IMAGENETOG_REST_API_ID``.

_Requirements: 2.2_
"""

import pytest

pytestmark = pytest.mark.integration


def test_stage_name_does_not_collide_with_path_prefix(
    apigateway_client: object,
    rest_api_id: str,
) -> None:
    resources = apigateway_client.get_resources(  # type: ignore[attr-defined]
        restApiId=rest_api_id, limit=500
    )
    # Path segments that are direct children of the API root (path has exactly
    # one '/'), e.g. "/v1" -> "v1".
    top_segments = {
        item["pathPart"]
        for item in resources.get("items", [])
        if item.get("path", "").count("/") == 1 and item.get("pathPart")
    }

    stages = apigateway_client.get_stages(restApiId=rest_api_id)  # type: ignore[attr-defined]
    stage_names = {s["stageName"] for s in stages.get("item", [])}

    collisions = stage_names & top_segments
    assert not collisions, (
        f"API Gateway stage name(s) {collisions} collide with a top-level resource "
        f"path segment {top_segments}. A stage named the same as a path prefix "
        "(e.g. 'v1') makes /{stage}/{segment}/... unroutable and yields "
        "403 IncompleteSignatureException. Rename the stage (e.g. to the env name)."
    )
