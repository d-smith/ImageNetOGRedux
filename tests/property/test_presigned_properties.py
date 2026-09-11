"""Property tests for the presigned-URL service path (task 15.3).

* Property 15: for any valid collection + valid image key, ``get_presigned_url``
  returns a non-empty URL string.
* Property 16: for any valid image lookup, ``generate_presigned_url`` is called
  with ``ExpiresIn=300`` (``config.PRESIGNED_URL_TTL_SECONDS``) — the TTL is
  never influenced by caller input.

_Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

Implementation note: the service binds its DynamoDB/S3 clients at import time.
We activate moto once for the module, create both tables, reload the service so
its module-level clients point at the mocked backend, and clear the tables
between examples. ``_s3.generate_presigned_url`` is monkeypatched with a Mock so
we can assert the exact ``ExpiresIn`` value on every call.
"""

import importlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from api_handler import config

_COLLECTION_NAME = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=3,
    max_size=20,
).filter(lambda s: s[0] != "-" and s[-1] != "-")

# Image keys: no ".." (path traversal is rejected upstream), non-empty.
_IMAGE_KEY = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_/.",
    min_size=1,
    max_size=60,
).filter(lambda s: ".." not in s)

# Populated by the module fixture.
_svc: Any = None
_collections_table: Any = None
_images_table: Any = None


@pytest.fixture(autouse=True, scope="module")
def _mocked_service() -> Iterator[None]:
    """Start moto for the module, create both tables, reload the service once."""
    global _svc, _collections_table, _images_table
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        _collections_table = dynamodb.create_table(
            TableName=config.COLLECTIONS_TABLE,
            KeySchema=[{"AttributeName": "collection_name", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "collection_name", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        _collections_table.wait_until_exists()
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

        from api_handler.services import images as svc

        _svc = importlib.reload(svc)
        yield


def _clear_tables() -> None:
    """Delete every item so each example starts from empty tables."""
    for item in _collections_table.scan().get("Items", []):
        _collections_table.delete_item(Key={"collection_name": item["collection_name"]})
    for item in _images_table.scan().get("Items", []):
        _images_table.delete_item(
            Key={"collection_name": item["collection_name"], "image_key": item["image_key"]}
        )


def _put_collection(name: str) -> None:
    _collections_table.put_item(
        Item={
            "collection_name": name,
            "created": "2024-01-01",
            "created_epoch": 1704067200,
            "_type": "COLLECTION",
            "s3_bucket": f"dev-imagenetog-{name}-images",
            "s3vector_bucket": f"dev-imagenetog-{name}-vectors",
        }
    )


def _put_image(name: str, key: str) -> None:
    _images_table.put_item(
        Item={
            "collection_name": name,
            "image_key": key,
            "date_added": "2024-01-01",
            "date_added_epoch": 1704067200,
            "description": None,
            "s3_bucket": f"dev-imagenetog-{name}-images",
            "s3vector_bucket": f"dev-imagenetog-{name}-vectors",
        }
    )


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(collection=_COLLECTION_NAME, image_key=_IMAGE_KEY)
def test_valid_lookup_returns_nonempty_url(collection: str, image_key: str) -> None:
    # Feature: aws-deployment-feature, Property 15: valid lookup yields a non-empty URL
    _clear_tables()
    _put_collection(collection)
    _put_image(collection, image_key)

    spy = Mock(return_value="https://signed.example.com/object")
    _svc._s3.generate_presigned_url = spy

    result = _svc.get_presigned_url(collection, image_key)

    assert result["key"] == image_key
    assert isinstance(result["url"], str)
    assert result["url"] != ""


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(collection=_COLLECTION_NAME, image_key=_IMAGE_KEY)
def test_expires_in_always_300(collection: str, image_key: str) -> None:
    # Feature: aws-deployment-feature, Property 16: ExpiresIn is always 300
    _clear_tables()
    _put_collection(collection)
    _put_image(collection, image_key)

    spy = Mock(return_value="https://signed.example.com/object")
    _svc._s3.generate_presigned_url = spy

    _svc.get_presigned_url(collection, image_key)

    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs["ExpiresIn"] == config.PRESIGNED_URL_TTL_SECONDS
    assert kwargs["ExpiresIn"] == 300
