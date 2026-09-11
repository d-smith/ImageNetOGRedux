"""Integration test (task 25.3): end-to-end ingestion workflow.

Uploads a small test image to an existing collection's S3 image bucket, which
triggers the EventBridge → Step Functions ingestion workflow, then polls the
DynamoDB images table until the metadata record appears (or a timeout), and
asserts all required non-null fields are present.

Prerequisites (see README "Integration tests"):
* A deployed stack with the ingestion workflow wired.
* An existing collection created via ``create_collection.py``
  (``IMAGENETOG_TEST_COLLECTION``); its image bucket must have EventBridge
  notifications enabled.

_Requirements: 12.1_
"""

import time
import uuid

import pytest

pytestmark = pytest.mark.integration

_POLL_TIMEOUT_SECONDS = 180
_POLL_INTERVAL_SECONDS = 5

# 1x1 transparent PNG (smallest valid image the describe/embed models accept).
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

_REQUIRED_FIELDS = (
    "collection_name",
    "image_key",
    "date_added",
    "date_added_epoch",
    "s3_bucket",
    "s3vector_bucket",
)


def test_upload_triggers_ingestion_record(
    s3_client: object,
    dynamodb_resource: object,
    test_collection: str,
    test_image_bucket: str,
    images_table_name: str,
) -> None:
    image_key = f"integration-tests/{uuid.uuid4().hex}.png"

    s3_client.put_object(  # type: ignore[attr-defined]
        Bucket=test_image_bucket,
        Key=image_key,
        Body=_PNG_1X1,
        ContentType="image/png",
    )

    table = dynamodb_resource.Table(images_table_name)  # type: ignore[attr-defined]

    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    item = None
    while time.monotonic() < deadline:
        response = table.get_item(Key={"collection_name": test_collection, "image_key": image_key})
        item = response.get("Item")
        if item is not None:
            break
        time.sleep(_POLL_INTERVAL_SECONDS)

    assert item is not None, (
        f"ingestion record for {image_key!r} did not appear in {images_table_name} "
        f"within {_POLL_TIMEOUT_SECONDS}s"
    )

    for field in _REQUIRED_FIELDS:
        assert field in item, f"missing required field {field!r} in {item}"
        assert item[field] is not None, f"required field {field!r} is null"
