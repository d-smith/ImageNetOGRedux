"""Integration test (task 25.4): presigned URL expiry enforcement.

Generates a presigned GET URL with a deliberately short 5-second TTL
(test-only override — the API always uses 300s), confirms it works immediately,
waits past expiry, and asserts S3 rejects the expired URL. This verifies S3
enforces signature expiry (Requirement 8.5 / 8.2).

Prerequisites: a deployed stack and an existing collection image bucket
(``IMAGENETOG_TEST_COLLECTION`` / ``IMAGENETOG_TEST_IMAGE_BUCKET``).

_Requirements: 8.5_
"""

import contextlib
import time
import uuid

import pytest
import requests

pytestmark = pytest.mark.integration

_TTL_SECONDS = 5
_WAIT_SECONDS = 7  # a little past TTL to avoid clock-skew flakiness
_HTTP_TIMEOUT = 15


def test_presigned_url_expires(
    s3_client: object,
    test_image_bucket: str,
) -> None:
    key = f"integration-tests/expiry-{uuid.uuid4().hex}.txt"
    s3_client.put_object(  # type: ignore[attr-defined]
        Bucket=test_image_bucket, Key=key, Body=b"expiry-test"
    )

    url = s3_client.generate_presigned_url(  # type: ignore[attr-defined]
        "get_object",
        Params={"Bucket": test_image_bucket, "Key": key},
        ExpiresIn=_TTL_SECONDS,
    )

    # Immediately valid.
    fresh = requests.get(url, timeout=_HTTP_TIMEOUT)
    assert fresh.status_code == 200, f"fresh presigned URL should work, got {fresh.status_code}"

    # After expiry, S3 must reject it.
    time.sleep(_WAIT_SECONDS)
    expired = requests.get(url, timeout=_HTTP_TIMEOUT)
    assert (
        expired.status_code == 403
    ), f"expired presigned URL should be rejected with 403, got {expired.status_code}"

    # Best-effort cleanup (must not fail the test).
    with contextlib.suppress(Exception):
        s3_client.delete_object(Bucket=test_image_bucket, Key=key)  # type: ignore[attr-defined]
