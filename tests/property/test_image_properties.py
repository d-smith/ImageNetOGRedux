"""Property tests for the images list service (task 14.2).

* Property 11: every image item returned by ``list_images`` has exactly ``key``,
  ``dateAdded``, and ``description`` (which may be ``None``) — and never the
  internal ``s3_bucket`` / ``s3vector_bucket`` fields.
* Property 12: on the date-only path, a valid date range returns only images
  whose ``date_added_epoch`` falls within ``[after, before]``. (Inverted ranges
  are rejected earlier at the parameter-validation layer — see
  ``tests/unit/test_param_validation.py::TestDateRange`` — so only valid ranges
  reach ``list_images``.)
* Property 13: every image key returned by the description (vector) search
  exists as a real image record within the collection — the result set is a
  subset of the collection's images.
* Property 14: the combined (description + date range) search returns only
  images whose ``dateAdded`` falls within the range.

Vector-search mocking: moto (5.1.22) does NOT implement ``s3vectors:QueryVectors``,
so Properties 13 and 14 stub the service's module-level ``_s3vectors`` client
with a fake ``query_vectors`` that mirrors the real contract (returns a ranked
subset of keys and honours the ``date_added_epoch`` ``$gte``/``$lte`` filter),
and stub ``_embed_description`` to avoid a real Bedrock call. DynamoDB stays
under moto, so ``batch_get_item`` hydration and the containment check are real.

_Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

Implementation note: the images service binds its DynamoDB clients at import
time. We activate moto once for the module, create the collections + images
tables (the images table includes the ``date_added_epoch-index`` LSI the
date-only path queries), reload the service so its module-level tables bind to
the mocked backend, and clear the tables between examples.
"""

import importlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from api_handler import config
from api_handler.params import DateRangeParams, PaginationParams

_COLLECTION = "nature-2024"
_DATE_INDEX = "date_added_epoch-index"

_ISO_DATE = st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31))

# Populated by the module fixture.
_svc: Any = None
_collections_table: Any = None
_images_table: Any = None


@pytest.fixture(autouse=True, scope="module")
def _mocked_service() -> Iterator[None]:
    """Start moto for the module, create both tables + LSI, reload the service."""
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
                {"AttributeName": "date_added_epoch", "AttributeType": "N"},
            ],
            LocalSecondaryIndexes=[
                {
                    "IndexName": _DATE_INDEX,
                    "KeySchema": [
                        {"AttributeName": "collection_name", "KeyType": "HASH"},
                        {"AttributeName": "date_added_epoch", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
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


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


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


def _put_image(key: str, d: date, description: str | None = None) -> None:
    _images_table.put_item(
        Item={
            "collection_name": _COLLECTION,
            "image_key": key,
            "date_added": d.isoformat(),
            "date_added_epoch": _epoch(d),
            "description": description,
            "s3_bucket": f"dev-imagenetog-{_COLLECTION}-images",
            "s3vector_bucket": f"dev-imagenetog-{_COLLECTION}-vectors",
        }
    )


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    dates=st.lists(_ISO_DATE, min_size=1, max_size=10),
    descriptions=st.lists(st.one_of(st.none(), st.text(max_size=40)), min_size=1, max_size=10),
)
def test_field_completeness_and_privacy(dates: list[date], descriptions: list[str | None]) -> None:
    # Feature: aws-deployment-feature, Property 11: image field completeness and privacy
    _clear_tables()
    _put_collection()
    for idx, d in enumerate(dates):
        desc = descriptions[idx % len(descriptions)]
        _put_image(f"img-{idx}.jpg", d, desc)

    result = _svc.list_images(
        collection_name=_COLLECTION,
        pagination=PaginationParams(limit=100, offset=0),
        date_range=DateRangeParams(after=None, before=None),
        description=None,
    )

    assert result["total"] == len(dates)
    for item in result["items"]:
        assert set(item.keys()) == {"key", "dateAdded", "description"}
        assert "s3_bucket" not in item
        assert "s3vector_bucket" not in item


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dates=st.lists(_ISO_DATE, min_size=1, max_size=10), lo=_ISO_DATE, hi=_ISO_DATE)
def test_date_range_filter(dates: list[date], lo: date, hi: date) -> None:
    # Feature: aws-deployment-feature, Property 12: image date-range filter correctness
    _clear_tables()
    _put_collection()
    after, before = (lo, hi) if lo <= hi else (hi, lo)

    keys_by_date: list[tuple[str, date]] = []
    for idx, d in enumerate(dates):
        key = f"img-{idx}.jpg"
        keys_by_date.append((key, d))
        _put_image(key, d)

    result = _svc.list_images(
        collection_name=_COLLECTION,
        pagination=PaginationParams(limit=100, offset=0),
        date_range=DateRangeParams(after=after, before=before),
        description=None,
    )

    returned = {item["key"] for item in result["items"]}
    expected = {key for key, d in keys_by_date if after <= d <= before}
    assert returned == expected


# ---------------------------------------------------------------------------
# Vector-search path (Properties 13 & 14)
#
# moto does not implement s3vectors:QueryVectors, so we stub the service's
# module-level ``_s3vectors`` client with a fake whose ``query_vectors`` mirrors
# the real contract: it returns a ranked subset of the vectors that were
# "indexed" for the collection, honouring the ``date_added_epoch`` metadata
# filter (``$gte`` / ``$lte``) exactly as the real S3 Vectors service would.
# DynamoDB stays under moto, so ``batch_get_item`` hydration is real and the
# containment assertion (Property 13) is meaningful.
# ---------------------------------------------------------------------------


class _FakeS3Vectors:
    """Minimal stand-in for the s3vectors client's ``query_vectors``.

    Args:
        indexed: The (image_key, date_added_epoch) pairs available in the
            index, in the ranked order the query should return them.
    """

    def __init__(self, indexed: list[tuple[str, int]]) -> None:
        self._indexed = indexed

    def query_vectors(
        self,
        *,
        vectorBucketName: str,  # noqa: N803 — boto3 param name
        indexName: str,  # noqa: N803
        topK: int,  # noqa: N803
        queryVector: dict[str, Any],  # noqa: N803
        filter: dict[str, Any] | None = None,  # noqa: A002 — boto3 param name
    ) -> dict[str, Any]:
        candidates = self._indexed
        if filter is not None:
            bounds = filter["date_added_epoch"]
            lo = bounds.get("$gte")
            hi = bounds.get("$lte")
            candidates = [
                (k, e)
                for (k, e) in candidates
                if (lo is None or e >= lo) and (hi is None or e <= hi)
            ]
        selected = candidates[:topK]
        return {"vectors": [{"key": k} for k, _ in selected]}


def _install_vector_stub(monkeypatch: pytest.MonkeyPatch, indexed: list[tuple[str, int]]) -> None:
    """Point the service's ``_s3vectors`` accessor at a fake, and stub embedding."""
    fake = _FakeS3Vectors(indexed)
    monkeypatch.setattr(_svc, "_s3vectors", lambda: fake)
    # Avoid a real Bedrock embed call; the fake ignores the query vector anyway.
    monkeypatch.setattr(_svc, "_embed_description", lambda _description: [0.0] * 1024)


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dates=st.lists(_ISO_DATE, min_size=1, max_size=10))
def test_vector_search_result_containment(
    dates: list[date], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature: aws-deployment-feature, Property 13: vector search result containment
    _clear_tables()
    _put_collection()

    indexed: list[tuple[str, int]] = []
    for idx, d in enumerate(dates):
        key = f"img-{idx}.jpg"
        _put_image(key, d)
        indexed.append((key, _epoch(d)))
    valid_keys = {k for k, _ in indexed}

    _install_vector_stub(monkeypatch, indexed)

    result = _svc.list_images(
        collection_name=_COLLECTION,
        pagination=PaginationParams(limit=100, offset=0),
        date_range=DateRangeParams(after=None, before=None),
        description="a mountain at dusk",
    )

    returned = {item["key"] for item in result["items"]}
    # Every returned key exists as a real image record in the collection.
    assert returned <= valid_keys
    # Field privacy still holds on the vector-search path.
    for item in result["items"]:
        assert set(item.keys()) == {"key", "dateAdded", "description"}


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(dates=st.lists(_ISO_DATE, min_size=1, max_size=10), lo=_ISO_DATE, hi=_ISO_DATE)
def test_combined_search_respects_date_filter(
    dates: list[date], lo: date, hi: date, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature: aws-deployment-feature, Property 14: combined search respects date filter
    _clear_tables()
    _put_collection()
    after, before = (lo, hi) if lo <= hi else (hi, lo)

    indexed: list[tuple[str, int]] = []
    dates_by_key: dict[str, date] = {}
    for idx, d in enumerate(dates):
        key = f"img-{idx}.jpg"
        _put_image(key, d)
        indexed.append((key, _epoch(d)))
        dates_by_key[key] = d

    _install_vector_stub(monkeypatch, indexed)

    result = _svc.list_images(
        collection_name=_COLLECTION,
        pagination=PaginationParams(limit=100, offset=0),
        date_range=DateRangeParams(after=after, before=before),
        description="a mountain at dusk",
    )

    # Every returned image's dateAdded falls within the requested range.
    for item in result["items"]:
        d = dates_by_key[item["key"]]
        assert after <= d <= before
