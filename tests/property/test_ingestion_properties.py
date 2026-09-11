"""Property tests for the ingestion store handler (task 19.2).

* Property 19: for any generated ``(collection, image)`` pair, after invoking
  ``ingestion.store.handler`` the persisted DynamoDB images record contains all
  required non-null fields: ``collection_name``, ``image_key``, ``date_added``,
  ``date_added_epoch``, ``s3_bucket``, and ``s3vector_bucket``. The
  ``description`` field is optional and may be ``None``.

_Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

Implementation note: ``ingestion.store`` binds its DynamoDB resource at import
time. We activate moto once for the module, create the images table, reload the
store module so its module-level table points at the mocked backend, and clear
the table between examples.
"""

import importlib
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from ingestion import config

_COLLECTION_NAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=3,
    max_size=20,
).filter(lambda s: s[0] != "-" and s[-1] != "-")

_IMAGE_KEY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_/.",
    min_size=1,
    max_size=60,
).filter(lambda s: ".." not in s)

_DESCRIPTION = st.one_of(st.none(), st.text(min_size=0, max_size=200))
_EPOCH = st.integers(min_value=946684800, max_value=1924991999)

_REQUIRED_FIELDS = (
    "collection_name",
    "image_key",
    "date_added",
    "date_added_epoch",
    "s3_bucket",
    "s3vector_bucket",
)

# Populated by the module fixture.
_store: Any = None
_images_table: Any = None


@pytest.fixture(autouse=True, scope="module")
def _mocked_store() -> Iterator[None]:
    """Start moto for the module, create the images table, reload store once."""
    global _store, _images_table
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _images_table = dynamodb.create_table(
            TableName=config.IMAGES_TABLE,
            KeySchema=[
                {"AttributeName": "collection_name", "KeyType": "HASH"},
                {"AttributeName": "image_key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "collection_name", "AttributeType": "S"},
                {"AttributeName": "image_key", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        _images_table.wait_until_exists()

        from ingestion import store

        _store = importlib.reload(store)  # rebind module-level table to the mock
        yield


def _clear_table() -> None:
    """Delete every item so each example starts from an empty table."""
    for item in _images_table.scan().get("Items", []):
        _images_table.delete_item(
            Key={"collection_name": item["collection_name"], "image_key": item["image_key"]}
        )


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    collection=_COLLECTION_NAME,
    image_key=_IMAGE_KEY,
    date_epoch=_EPOCH,
    description=_DESCRIPTION,
)
def test_store_persists_all_required_fields(
    collection: str,
    image_key: str,
    date_epoch: int,
    description: str | None,
) -> None:
    # Feature: aws-deployment-feature, Property 19: stored record has all required fields
    _clear_table()

    date_added = "2024-01-01"
    event: dict[str, Any] = {
        "collection_name": collection,
        "image_key": image_key,
        "date_added": date_added,
        "date_added_epoch": date_epoch,
        "description": description,
        "s3_bucket": f"dev-imagenetog-{collection}-images",
        "s3vector_bucket": f"dev-imagenetog-{collection}-vectors",
    }

    returned = _store.handler(event, None)
    assert returned == event

    response = _images_table.get_item(Key={"collection_name": collection, "image_key": image_key})
    item = response.get("Item")
    assert item is not None

    for field in _REQUIRED_FIELDS:
        assert field in item, f"missing required field: {field}"
        assert item[field] is not None, f"required field is null: {field}"

    # date_added_epoch is persisted as a number.
    assert int(item["date_added_epoch"]) == date_epoch
    # description is allowed to be null.
    assert "description" in item
