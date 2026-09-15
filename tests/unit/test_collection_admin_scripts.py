"""Unit tests for the ``delete_collection`` and ``list_collections`` scripts.

Both scripts build their boto3 clients inside their functions with an explicit
``region_name``, so they bind to the moto-mocked backend naturally under
``@mock_aws`` (no module reload needed). moto 5.1.22 implements the s3vectors
create/delete operations and standard S3/DynamoDB, so the flows are exercised
end to end without a live account.
"""

import importlib
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

_ENV = "dev"
_COLLECTION = "nature-2024"
_COLLECTIONS_TABLE = f"{_ENV}-imagenetog-collections"
_IMAGE_BUCKET = f"{_ENV}-imagenetog-{_COLLECTION}-images"
_VECTOR_BUCKET = f"{_ENV}-imagenetog-{_COLLECTION}-vectors"


@pytest.fixture
def _aws() -> Iterator[None]:
    with mock_aws():
        yield


def _create_collections_table() -> Any:
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.create_table(
        TableName=_COLLECTIONS_TABLE,
        KeySchema=[{"AttributeName": "collection_name", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "collection_name", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


def _provision_collection() -> None:
    """Create the full set of resources delete_collection expects to remove."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=_IMAGE_BUCKET)
    s3.put_object(Bucket=_IMAGE_BUCKET, Key="uploads/a.jpg", Body=b"x")

    s3v = boto3.client("s3vectors", region_name="us-east-1")
    s3v.create_vector_bucket(vectorBucketName=_VECTOR_BUCKET)
    s3v.create_index(
        vectorBucketName=_VECTOR_BUCKET,
        indexName="images",
        dataType="float32",
        dimension=1024,
        distanceMetric="cosine",
    )

    table = _create_collections_table()
    table.put_item(
        Item={
            "collection_name": _COLLECTION,
            "created": "2024-01-01",
            "created_epoch": 1704067200,
            "_type": "COLLECTION",
            "s3_bucket": _IMAGE_BUCKET,
            "s3vector_bucket": _VECTOR_BUCKET,
        }
    )


class TestDeleteCollection:
    def test_deletes_all_resources(self, _aws: None) -> None:
        from scripts import delete_collection as dc

        importlib.reload(dc)
        _provision_collection()

        dc.delete_collection(_COLLECTION, _ENV)

        s3 = boto3.client("s3", region_name="us-east-1")
        existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
        assert _IMAGE_BUCKET not in existing

        s3v = boto3.client("s3vectors", region_name="us-east-1")
        vbs = {b["vectorBucketName"] for b in s3v.list_vector_buckets().get("vectorBuckets", [])}
        assert _VECTOR_BUCKET not in vbs

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        item = dynamodb.Table(_COLLECTIONS_TABLE).get_item(Key={"collection_name": _COLLECTION})
        assert "Item" not in item

    def test_idempotent_when_nothing_exists(self, _aws: None) -> None:
        from scripts import delete_collection as dc

        importlib.reload(dc)
        # Only the collections table exists; buckets/index absent.
        _create_collections_table()

        # Should not raise even though the buckets/index never existed.
        dc.delete_collection(_COLLECTION, _ENV)

    def test_main_aborts_without_confirmation(self, _aws: None) -> None:
        from scripts import delete_collection as dc

        importlib.reload(dc)
        _provision_collection()

        # No --yes and no interactive tty (input raises EOFError) -> abort, rc=1.
        rc = dc.main(["--collection-name", _COLLECTION, "--env", _ENV])
        assert rc == 1

        # The image bucket must still exist (nothing was deleted).
        s3 = boto3.client("s3", region_name="us-east-1")
        existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
        assert _IMAGE_BUCKET in existing

    def test_main_deletes_with_yes(self, _aws: None) -> None:
        from scripts import delete_collection as dc

        importlib.reload(dc)
        _provision_collection()

        rc = dc.main(["--collection-name", _COLLECTION, "--env", _ENV, "--yes"])
        assert rc == 0

        s3 = boto3.client("s3", region_name="us-east-1")
        existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
        assert _IMAGE_BUCKET not in existing


class TestListCollections:
    def test_reports_registered_and_no_orphans(self, _aws: None) -> None:
        from scripts import list_collections as lc

        importlib.reload(lc)
        _provision_collection()

        orphans = lc.list_collections(_ENV)
        assert orphans == 0

    def test_flags_orphan_bucket(self, _aws: None) -> None:
        from scripts import list_collections as lc

        importlib.reload(lc)
        _create_collections_table()  # table exists but has no records
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_IMAGE_BUCKET)  # bucket with no DynamoDB record

        orphans = lc.list_collections(_ENV)
        assert orphans == 1

    def test_missing_table_treats_buckets_as_orphans(self, _aws: None) -> None:
        from scripts import list_collections as lc

        importlib.reload(lc)
        # No collections table at all (simulates post-terraform-destroy).
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_IMAGE_BUCKET)
        s3.create_bucket(Bucket=_VECTOR_BUCKET)  # plain S3 bucket named like a vector bucket

        orphans = lc.list_collections(_ENV)
        assert orphans == 1  # same collection name from both bucket kinds -> one orphan
