"""Unit tests for the presigned-URL service path (task 15.2).

Covers :func:`api_handler.services.images.get_presigned_url`:

* The generated URL uses ``ExpiresIn=config.PRESIGNED_URL_TTL_SECONDS`` (300)
  exactly (the caller may never influence the TTL).
* A missing collection raises ``CollectionNotFoundError`` (404).
* A missing image key raises ``ImageNotFoundError`` (404).

Implementation note (moto/reload): the service binds its DynamoDB and S3
clients at import time (outside moto). We enter ``mock_aws`` first, create both
tables, then ``importlib.reload`` the service so its module-level clients bind
to the mocked backend. ``generate_presigned_url`` is spied via a
``unittest.mock.Mock`` so we can assert the exact ``ExpiresIn`` value.

_Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
"""

import importlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from api_handler import config
from api_handler.exceptions import CollectionNotFoundError, ImageNotFoundError

_COLLECTION = "nature-2024"
_IMAGE_KEY = "photos/img-001.jpg"

# Populated by the fixture: the reloaded service module and the mocked tables.
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

        _svc = importlib.reload(svc)  # rebind module-level clients to the mock
        yield


def _clear_tables() -> None:
    """Delete every item so each test starts from empty tables."""
    for item in _collections_table.scan().get("Items", []):
        _collections_table.delete_item(Key={"collection_name": item["collection_name"]})
    for item in _images_table.scan().get("Items", []):
        _images_table.delete_item(
            Key={"collection_name": item["collection_name"], "image_key": item["image_key"]}
        )


def _put_collection(name: str = _COLLECTION) -> None:
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


def _put_image(name: str = _COLLECTION, key: str = _IMAGE_KEY) -> None:
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


def test_expires_in_is_300(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tables()
    _put_collection()
    _put_image()

    spy = Mock(return_value="https://example.com/signed")
    monkeypatch.setattr(_svc._s3, "generate_presigned_url", spy)

    result = _svc.get_presigned_url(_COLLECTION, _IMAGE_KEY)

    assert result["key"] == _IMAGE_KEY
    assert result["url"] == "https://example.com/signed"
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs["ExpiresIn"] == config.PRESIGNED_URL_TTL_SECONDS
    assert kwargs["ExpiresIn"] == 300


def test_bucket_comes_from_collection_record(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tables()
    _put_collection()
    _put_image()

    spy = Mock(return_value="https://example.com/signed")
    monkeypatch.setattr(_svc._s3, "generate_presigned_url", spy)

    _svc.get_presigned_url(_COLLECTION, _IMAGE_KEY)

    _, kwargs = spy.call_args
    assert kwargs["Params"]["Bucket"] == f"dev-imagenetog-{_COLLECTION}-images"
    assert kwargs["Params"]["Key"] == _IMAGE_KEY


def test_missing_collection_raises_404() -> None:
    _clear_tables()
    # No collection record written.
    with pytest.raises(CollectionNotFoundError) as exc:
        _svc.get_presigned_url(_COLLECTION, _IMAGE_KEY)
    assert exc.value.http_status == 404


def test_missing_image_raises_404() -> None:
    _clear_tables()
    _put_collection()
    # Collection exists but the image key does not.
    with pytest.raises(ImageNotFoundError) as exc:
        _svc.get_presigned_url(_COLLECTION, "does/not/exist.jpg")
    assert exc.value.http_status == 404
